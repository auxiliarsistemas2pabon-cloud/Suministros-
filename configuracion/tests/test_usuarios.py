from django.contrib.auth import SESSION_KEY
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from bitacora.models import RegistroBitacora
from configuracion.tests.base import CLAVE, MOTIVO, BasePanel, Rol, Usuario, crear_usuario
from cuentas import servicios

CLAVE_MANUAL = "Temporal-Ficticia-93"


def datos_usuario(**cambios):
    datos = {
        "correo": "Nuevo.Usuario@Ejemplo.test",
        "nombre": "Nuevo Usuario",
        "rol": Rol.COORDINADOR,
        "area": "",
        "modo_clave": "generar",
        "motivo": MOTIVO,
    }
    datos.update(cambios)
    return datos


class UsuariosListaTests(BasePanel):
    def test_filtros_por_rol_area_estado_y_busqueda(self):
        url = reverse("configuracion:usuarios")
        respuesta = self.client.get(url, {"rol": Rol.COORDINADOR})
        self.assertContains(respuesta, "coord@ejemplo.test")
        self.assertNotContains(respuesta, "prov@ejemplo.test")
        respuesta = self.client.get(url, {"area": self.area.pk})
        self.assertContains(respuesta, "coord@ejemplo.test")
        self.assertNotContains(respuesta, "dev@ejemplo.test")
        Usuario.objects.filter(pk=self.proveedor.pk).update(activo=False)
        respuesta = self.client.get(url, {"estado": "inactivos"})
        self.assertContains(respuesta, "prov@ejemplo.test")
        self.assertNotContains(respuesta, "coord@ejemplo.test")
        respuesta = self.client.get(url, {"q": "dev@"})
        self.assertContains(respuesta, "dev@ejemplo.test")
        self.assertNotContains(respuesta, "coord@ejemplo.test")

    def test_administrador_ve_desarrolladores_sin_acciones(self):
        respuesta = self.client.get(reverse("configuracion:usuarios"))
        self.assertContains(respuesta, "dev@ejemplo.test")
        self.assertContains(respuesta, "Solo un desarrollador puede modificarlo")
        self.assertNotContains(respuesta, reverse("configuracion:usuario_editar", args=[self.desarrollador.pk]))

    def test_paginacion(self):
        for numero in range(30):
            crear_usuario(Rol.PROVEEDOR, correo=f"prov{numero}@ejemplo.test")
        respuesta = self.client.get(reverse("configuracion:usuarios"), {"rol": Rol.PROVEEDOR})
        self.assertContains(respuesta, "Página 1 de 2")
        respuesta = self.client.get(reverse("configuracion:usuarios"), {"rol": Rol.PROVEEDOR, "pagina": 2})
        self.assertContains(respuesta, "Página 2 de 2")


class CrearUsuarioTests(BasePanel):
    url = "/configuracion/usuarios/nuevo/"

    def test_crear_con_clave_generada_que_se_muestra_una_sola_vez(self):
        respuesta = self.client.post(self.url, datos_usuario(area=self.area.pk))
        nuevo = Usuario.objects.get(correo="nuevo.usuario@ejemplo.test")
        destino = reverse("configuracion:usuario_clave_temporal", args=[nuevo.pk])
        # Sin abrir el destino aquí: abrirlo consumiría la clave que se muestra una sola vez.
        self.assertRedirects(respuesta, destino, fetch_redirect_response=False)
        self.assertTrue(nuevo.debe_cambiar_clave)
        self.assertFalse(nuevo.is_staff)
        self.assertEqual(nuevo.area, self.area)

        respuesta = self.client.get(destino)
        self.assertIn("no-store", respuesta["Cache-Control"])
        clave = respuesta.context["clave"]
        self.assertEqual(len(clave), servicios.LONGITUD_CLAVE_TEMPORAL)
        self.assertContains(respuesta, clave)
        self.assertTrue(self.recargar(nuevo).check_password(clave))
        # Segunda visita: ya no se muestra.
        segunda = self.client.get(destino, follow=True)
        self.assertNotContains(segunda, clave)
        self.assertContains(segunda, "ya se mostró")
        # La clave no queda en la bitácora.
        registro = RegistroBitacora.objects.get(accion="usuario.creado")
        self.assertNotIn(clave, str(registro.valor_nuevo))
        self.assertEqual(registro.motivo, MOTIVO)

    def test_el_usuario_creado_debe_cambiar_la_clave_al_ingresar(self):
        self.client.post(self.url, datos_usuario(area=self.area.pk, modo_clave="manual", clave1=CLAVE_MANUAL, clave2=CLAVE_MANUAL))
        cliente = Client()
        respuesta = cliente.post("/ingresar/", {"username": "nuevo.usuario@ejemplo.test", "password": CLAVE_MANUAL}, follow=True)
        self.assertEqual(respuesta.redirect_chain[-1][0], "/cambiar-clave/")

    def test_crear_con_clave_manual(self):
        respuesta = self.client.post(
            self.url,
            datos_usuario(
                rol=Rol.PROVEEDOR,
                proveedor=self.proveedor.proveedor_id,
                modo_clave="manual",
                clave1=CLAVE_MANUAL,
                clave2=CLAVE_MANUAL,
            ),
        )
        self.assertRedirects(respuesta, reverse("configuracion:usuarios"))
        nuevo = Usuario.objects.get(correo="nuevo.usuario@ejemplo.test")
        self.assertTrue(nuevo.check_password(CLAVE_MANUAL))
        self.assertTrue(nuevo.debe_cambiar_clave)
        self.assertEqual(nuevo.proveedor_id, self.proveedor.proveedor_id)

    def test_clave_manual_validada(self):
        respuesta = self.client.post(self.url, datos_usuario(rol=Rol.PROVEEDOR, modo_clave="manual", clave1="123", clave2="123"))
        self.assertContains(respuesta, "demasiado corta")
        respuesta = self.client.post(
            self.url, datos_usuario(rol=Rol.PROVEEDOR, modo_clave="manual", clave1=CLAVE_MANUAL, clave2="otra")
        )
        self.assertContains(respuesta, "Las dos claves no coinciden")
        respuesta = self.client.post(self.url, datos_usuario(rol=Rol.PROVEEDOR, modo_clave="manual"))
        self.assertContains(respuesta, "Escriba la clave temporal")
        self.assertFalse(Usuario.objects.filter(correo="nuevo.usuario@ejemplo.test").exists())

    def test_reglas_de_rol_y_area(self):
        respuesta = self.client.post(self.url, datos_usuario(area=""))
        self.assertContains(respuesta, "Un coordinador debe tener un área asignada.")
        respuesta = self.client.post(self.url, datos_usuario(rol=Rol.PROVEEDOR, area=self.area.pk))
        self.assertContains(respuesta, "Un proveedor no puede tener área.")
        respuesta = self.client.post(self.url, datos_usuario(correo="COORD@ejemplo.test", area=self.area.pk))
        self.assertContains(respuesta, "Ya existe un usuario con este correo.")
        respuesta = self.client.post(self.url, datos_usuario(area=self.area.pk, motivo=""))
        self.assertContains(respuesta, "Indique el motivo del cambio")
        self.assertFalse(Usuario.objects.filter(correo="nuevo.usuario@ejemplo.test").exists())


class ReglaDesarrolladorTests(BasePanel):
    """Un administrador no puede crear, editar ni promover desarrolladores."""

    def test_administrador_no_ve_la_opcion_desarrollador(self):
        respuesta = self.client.get(reverse("configuracion:usuario_nuevo"))
        opciones = [valor for valor, _ in respuesta.context["formulario"].fields["rol"].choices]
        self.assertNotIn(Rol.DESARROLLADOR, opciones)
        self.assertIn(Rol.ADMINISTRADOR, opciones)

    def test_administrador_no_puede_crear_desarrollador(self):
        respuesta = self.client.post(reverse("configuracion:usuario_nuevo"), datos_usuario(rol=Rol.DESARROLLADOR))
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["formulario"].errors["rol"])
        self.assertFalse(Usuario.objects.filter(correo="nuevo.usuario@ejemplo.test").exists())

    def test_administrador_no_puede_promover_a_desarrollador(self):
        url = reverse("configuracion:usuario_editar", args=[self.proveedor.pk])
        respuesta = self.client.post(
            url, {"correo": self.proveedor.correo, "nombre": "X", "rol": Rol.DESARROLLADOR, "area": "", "motivo": MOTIVO}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(respuesta.context["formulario"].errors["rol"])
        self.assertEqual(self.recargar(self.proveedor).rol, Rol.PROVEEDOR)

    def test_administrador_recibe_403_sobre_un_desarrollador(self):
        for nombre in ("usuario_editar", "usuario_estado", "usuario_restablecer_clave"):
            url = reverse(f"configuracion:{nombre}", args=[self.desarrollador.pk])
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(
                    self.client.post(url, {"correo": "x@ejemplo.test", "nombre": "X", "rol": Rol.ADMINISTRADOR, "motivo": MOTIVO}).status_code,
                    403,
                )
        desarrollador = self.recargar(self.desarrollador)
        self.assertEqual(desarrollador.rol, Rol.DESARROLLADOR)
        self.assertTrue(desarrollador.activo)
        self.assertTrue(desarrollador.check_password(CLAVE))

    def test_el_servicio_tambien_lo_impide(self):
        """Aunque alguien se salte el formulario, el servicio rechaza la acción."""
        nuevo = Usuario(correo="otro.dev@ejemplo.test", nombre="Otro", rol=Rol.DESARROLLADOR)
        with self.assertRaises(PermissionDenied):
            servicios.crear_usuario(nuevo, actor=self.administrador, motivo=MOTIVO)
        self.proveedor.rol = Rol.DESARROLLADOR
        with self.assertRaises(PermissionDenied):
            servicios.editar_usuario(self.proveedor, actor=self.administrador, motivo=MOTIVO)
        self.desarrollador.nombre = "Cambiado"
        with self.assertRaises(PermissionDenied):
            servicios.editar_usuario(self.desarrollador, actor=self.administrador, motivo=MOTIVO)
        for accion in (
            lambda: servicios.cambiar_estado_usuario(self.desarrollador, False, actor=self.administrador, motivo=MOTIVO),
            lambda: servicios.restablecer_clave(self.desarrollador, actor=self.administrador, motivo=MOTIVO),
        ):
            with self.assertRaises(PermissionDenied):
                accion()
        self.assertFalse(Usuario.objects.filter(correo="otro.dev@ejemplo.test").exists())
        self.assertEqual(Usuario.objects.get(pk=self.proveedor.pk).rol, Rol.PROVEEDOR)
        self.assertEqual(Usuario.objects.get(pk=self.desarrollador.pk).nombre, "Usuario Desarrollador")

    def test_desarrollador_si_puede(self):
        self.como(self.desarrollador)
        respuesta = self.client.post(
            reverse("configuracion:usuario_nuevo"),
            datos_usuario(rol=Rol.DESARROLLADOR, modo_clave="manual", clave1=CLAVE_MANUAL, clave2=CLAVE_MANUAL),
        )
        self.assertRedirects(respuesta, reverse("configuracion:usuarios"))
        nuevo = Usuario.objects.get(correo="nuevo.usuario@ejemplo.test")
        self.assertEqual(nuevo.rol, Rol.DESARROLLADOR)
        # El panel nunca da acceso al admin técnico.
        self.assertFalse(nuevo.is_staff)
        self.assertFalse(nuevo.is_superuser)
        respuesta = self.client.post(
            reverse("configuracion:usuario_editar", args=[self.proveedor.pk]),
            {"correo": self.proveedor.correo, "nombre": "Promovido", "rol": Rol.DESARROLLADOR, "area": "", "motivo": MOTIVO},
        )
        self.assertRedirects(respuesta, reverse("configuracion:usuarios"))
        self.assertEqual(self.recargar(self.proveedor).rol, Rol.DESARROLLADOR)


class EditarUsuarioTests(BasePanel):
    def test_editar_registra_anterior_y_nuevo(self):
        url = reverse("configuracion:usuario_editar", args=[self.coordinador.pk])
        respuesta = self.client.post(
            url,
            {"correo": "Coord@Ejemplo.test", "nombre": "Coordinadora Farmacia", "rol": Rol.COORDINADOR, "area": self.otra_area.pk, "motivo": MOTIVO},
        )
        self.assertRedirects(respuesta, reverse("configuracion:usuarios"))
        coordinador = self.recargar(self.coordinador)
        self.assertEqual(coordinador.nombre, "Coordinadora Farmacia")
        self.assertEqual(coordinador.correo, "coord@ejemplo.test")
        self.assertEqual(coordinador.area, self.otra_area)
        registro = RegistroBitacora.objects.get(accion="usuario.modificado")
        self.assertEqual(set(registro.valor_nuevo), {"nombre", "area"})
        self.assertEqual(registro.motivo, MOTIVO)

    def test_no_puede_cambiar_su_propio_rol(self):
        url = reverse("configuracion:usuario_editar", args=[self.administrador.pk])
        respuesta = self.client.get(url)
        self.assertTrue(respuesta.context["formulario"].fields["rol"].disabled)
        self.client.post(
            url, {"correo": self.administrador.correo, "nombre": "Yo", "rol": Rol.PROVEEDOR, "area": "", "motivo": MOTIVO}
        )
        administrador = self.recargar(self.administrador)
        self.assertEqual(administrador.rol, Rol.ADMINISTRADOR)
        self.assertEqual(administrador.nombre, "Yo")
        # También en el servicio, aunque el objeto editado sea el mismo actor.
        actor = Usuario.objects.get(pk=self.administrador.pk)
        objetivo = Usuario.objects.get(pk=self.administrador.pk)
        objetivo.rol = Rol.COORDINADOR
        objetivo.area = self.area
        with self.assertRaises(ValidationError) as contexto:
            servicios.editar_usuario(objetivo, actor=actor, motivo=MOTIVO)
        self.assertIn("No puede cambiar su propio rol.", contexto.exception.messages)
        self.assertEqual(Usuario.objects.get(pk=self.administrador.pk).rol, Rol.ADMINISTRADOR)

    def test_edicion_no_cambia_estado_ni_privilegios(self):
        self.como(self.desarrollador)
        superusuario = Usuario.objects.create_superuser(correo="raiz@ejemplo.test", password=CLAVE, nombre="Raíz")
        respuesta = self.client.post(
            reverse("configuracion:usuario_editar", args=[superusuario.pk]),
            {"correo": superusuario.correo, "nombre": "Raíz", "rol": Rol.DESARROLLADOR, "area": "", "motivo": MOTIVO,
             "is_superuser": "", "is_staff": "", "activo": ""},
        )
        self.assertRedirects(respuesta, reverse("configuracion:usuarios"))
        superusuario = self.recargar(superusuario)
        self.assertTrue(superusuario.is_superuser)
        self.assertTrue(superusuario.activo)

    def test_quitar_rol_desarrollador_a_un_superusuario_muestra_error(self):
        self.como(self.desarrollador)
        superusuario = Usuario.objects.create_superuser(correo="raiz@ejemplo.test", password=CLAVE, nombre="Raíz")
        respuesta = self.client.post(
            reverse("configuracion:usuario_editar", args=[superusuario.pk]),
            {"correo": superusuario.correo, "nombre": "Raíz", "rol": Rol.ADMINISTRADOR, "area": "", "motivo": MOTIVO},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Solo los desarrolladores pueden")
        self.assertEqual(self.recargar(superusuario).rol, Rol.DESARROLLADOR)


class EstadoUsuarioTests(BasePanel):
    def test_desactivar_y_activar(self):
        url = reverse("configuracion:usuario_estado", args=[self.proveedor.pk])
        self.assertRedirects(self.client.post(url, {"motivo": MOTIVO}), reverse("configuracion:usuarios"))
        self.assertFalse(self.recargar(self.proveedor).activo)
        self.assertTrue(Usuario.objects.filter(pk=self.proveedor.pk).exists())
        self.assertTrue(RegistroBitacora.objects.filter(accion="usuario.desactivado").exists())
        self.assertRedirects(self.client.post(url, {"motivo": "Regresa"}), reverse("configuracion:usuarios"))
        self.assertTrue(self.recargar(self.proveedor).activo)
        self.assertTrue(RegistroBitacora.objects.filter(accion="usuario.activado").exists())

    def test_usuario_desactivado_pierde_la_sesion(self):
        cliente = Client()
        cliente.force_login(self.proveedor)
        self.client.post(reverse("configuracion:usuario_estado", args=[self.proveedor.pk]), {"motivo": MOTIVO})
        self.assertEqual(cliente.get("/portal/").status_code, 302)

    def test_no_puede_desactivarse_a_si_mismo(self):
        url = reverse("configuracion:usuario_estado", args=[self.administrador.pk])
        self.assertContains(self.client.get(url), "No puede desactivar su propia cuenta.")
        self.client.post(url, {"motivo": MOTIVO})
        self.assertTrue(self.recargar(self.administrador).activo)

    def test_estado_exige_motivo(self):
        url = reverse("configuracion:usuario_estado", args=[self.proveedor.pk])
        self.assertContains(self.client.post(url, {"motivo": " "}), "Indique el motivo del cambio")
        self.assertTrue(self.recargar(self.proveedor).activo)


class RestablecerClaveTests(BasePanel):
    def test_restablecer_con_clave_generada(self):
        otra_sesion = Client()
        otra_sesion.force_login(self.coordinador)
        url = reverse("configuracion:usuario_restablecer_clave", args=[self.coordinador.pk])
        respuesta = self.client.post(url, {"modo_clave": "generar", "motivo": "Olvidó su clave"})
        destino = reverse("configuracion:usuario_clave_temporal", args=[self.coordinador.pk])
        self.assertRedirects(respuesta, destino, fetch_redirect_response=False)
        clave = self.client.get(destino).context["clave"]
        coordinador = self.recargar(self.coordinador)
        self.assertTrue(coordinador.check_password(clave))
        self.assertTrue(coordinador.debe_cambiar_clave)
        registro = RegistroBitacora.objects.get(accion="cuenta.clave_restablecida")
        self.assertEqual(registro.motivo, "Olvidó su clave")
        self.assertNotIn(clave, str(registro.valor_nuevo))
        # La sesión que el coordinador tenía abierta se cierra.
        self.assertEqual(otra_sesion.get("/").status_code, 302)
        self.assertNotIn(SESSION_KEY, otra_sesion.session)

    def test_restablecer_con_clave_manual(self):
        url = reverse("configuracion:usuario_restablecer_clave", args=[self.coordinador.pk])
        respuesta = self.client.post(
            url, {"modo_clave": "manual", "clave1": CLAVE_MANUAL, "clave2": CLAVE_MANUAL, "motivo": MOTIVO}
        )
        self.assertRedirects(respuesta, reverse("configuracion:usuarios"))
        self.assertTrue(self.recargar(self.coordinador).check_password(CLAVE_MANUAL))

    def test_restablecer_exige_motivo(self):
        url = reverse("configuracion:usuario_restablecer_clave", args=[self.coordinador.pk])
        self.assertContains(self.client.post(url, {"modo_clave": "generar"}), "Indique el motivo del cambio")
        self.assertTrue(self.recargar(self.coordinador).check_password(CLAVE))

    def test_no_puede_restablecer_su_propia_clave(self):
        url = reverse("configuracion:usuario_restablecer_clave", args=[self.administrador.pk])
        self.assertRedirects(self.client.get(url), reverse("cuentas:cambiar_clave"))
        self.client.post(url, {"modo_clave": "generar", "motivo": MOTIVO})
        self.assertTrue(self.recargar(self.administrador).check_password(CLAVE))

    def test_clave_temporal_de_otro_usuario_no_se_muestra(self):
        url = reverse("configuracion:usuario_restablecer_clave", args=[self.coordinador.pk])
        self.client.post(url, {"modo_clave": "generar", "motivo": MOTIVO})
        otra = self.client.get(reverse("configuracion:usuario_clave_temporal", args=[self.proveedor.pk]), follow=True)
        self.assertContains(otra, "ya se mostró")


class ClaveTemporalTests(BasePanel):
    def test_genera_claves_que_cumplen_los_validadores(self):
        from django.contrib.auth.password_validation import validate_password

        claves = {servicios.generar_clave_temporal(self.coordinador) for _ in range(20)}
        self.assertEqual(len(claves), 20)
        for clave in claves:
            validate_password(clave, self.coordinador)
            self.assertEqual(len(clave), servicios.LONGITUD_CLAVE_TEMPORAL)
            self.assertFalse(set(clave) & set("O0l1I"))

from django.urls import reverse

from areas.models import Area
from bitacora.models import RegistroBitacora
from configuracion.tests.base import MOTIVO, BasePanel, Rol, Usuario, crear_usuario


class AreasCrudTests(BasePanel):
    def test_listado_con_filtro(self):
        respuesta = self.client.get(reverse("configuracion:areas"), {"q": "farm"})
        self.assertContains(respuesta, "Farmacia")
        self.assertNotContains(respuesta, "Laboratorio")
        self.recargar(self.otra_area)
        Area.objects.filter(pk=self.otra_area.pk).update(activa=False)
        respuesta = self.client.get(reverse("configuracion:areas"), {"estado": "inactivos"})
        self.assertContains(respuesta, "Laboratorio")
        self.assertNotContains(respuesta, "Farmacia")

    def test_crear_area(self):
        respuesta = self.client.post(
            reverse("configuracion:area_nueva"), {"nombre": "  Urgencias  ", "codigo_area": "urg", "motivo": MOTIVO}
        )
        self.assertRedirects(respuesta, reverse("configuracion:areas"))
        area = Area.objects.get(codigo_area="URG")
        self.assertEqual(area.nombre, "Urgencias")
        self.assertTrue(area.activa)
        registro = RegistroBitacora.objects.get(accion="area.creada")
        self.assertEqual(registro.actor, self.administrador)
        self.assertEqual(registro.motivo, MOTIVO)

    def test_crear_sin_motivo_o_duplicada_muestra_error(self):
        respuesta = self.client.post(reverse("configuracion:area_nueva"), {"nombre": "Urgencias", "codigo_area": "URG"})
        self.assertContains(respuesta, "Indique el motivo del cambio")
        respuesta = self.client.post(
            reverse("configuracion:area_nueva"), {"nombre": "FARMACIA", "codigo_area": "far", "motivo": MOTIVO}
        )
        self.assertContains(respuesta, "Ya existe un área con este nombre.")
        self.assertContains(respuesta, "Ya existe un área con este código.")
        self.assertEqual(Area.objects.count(), 2)

    def test_editar_area(self):
        respuesta = self.client.post(
            reverse("configuracion:area_editar", args=[self.area.pk]),
            {"nombre": "Farmacia Central", "codigo_area": "FAR", "motivo": MOTIVO},
        )
        self.assertRedirects(respuesta, reverse("configuracion:areas"))
        self.assertEqual(self.recargar(self.area).nombre, "Farmacia Central")
        registro = RegistroBitacora.objects.get(accion="area.modificada")
        self.assertEqual(registro.valor_anterior, {"nombre": "Farmacia"})
        self.assertEqual(registro.valor_nuevo, {"nombre": "Farmacia Central"})

    def test_desactivar_y_activar_area_sin_coordinadores(self):
        url = reverse("configuracion:area_estado", args=[self.otra_area.pk])
        self.assertContains(self.client.get(url), "Desactivar el área")
        self.assertRedirects(self.client.post(url, {"motivo": MOTIVO}), reverse("configuracion:areas"))
        self.assertFalse(self.recargar(self.otra_area).activa)
        self.assertTrue(RegistroBitacora.objects.filter(accion="area.desactivada").exists())
        self.assertRedirects(self.client.post(url, {"motivo": "Reapertura"}), reverse("configuracion:areas"))
        self.assertTrue(self.recargar(self.otra_area).activa)
        self.assertTrue(RegistroBitacora.objects.filter(accion="area.activada").exists())

    def test_desactivar_exige_motivo(self):
        url = reverse("configuracion:area_estado", args=[self.otra_area.pk])
        self.assertContains(self.client.post(url, {"motivo": ""}), "Indique el motivo del cambio")
        self.assertTrue(self.recargar(self.otra_area).activa)

    def test_desactivar_area_con_coordinadores_activos_se_bloquea(self):
        url = reverse("configuracion:area_estado", args=[self.area.pk])
        respuesta = self.client.get(url)
        self.assertContains(respuesta, "tiene 1 coordinador activo")
        respuesta = self.client.post(url, {"motivo": MOTIVO})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Reasígnelos a otra área o desactívelos primero")
        self.assertTrue(self.recargar(self.area).activa)

    def test_desactivar_area_no_borra_datos(self):
        # Un coordinador inactivo (que conserva el área) no bloquea la desactivación.
        Usuario.objects.filter(pk=self.coordinador.pk).update(activo=False)
        url = reverse("configuracion:area_estado", args=[self.area.pk])
        self.assertRedirects(self.client.post(url, {"motivo": MOTIVO}), reverse("configuracion:areas"))
        area = Area.objects.get(pk=self.area.pk)
        self.assertFalse(area.activa)
        self.assertEqual(area.nombre, "Farmacia")
        coordinador = self.recargar(self.coordinador)
        self.assertEqual(coordinador.area, area)
        self.assertEqual(Area.objects.count(), 2)
        self.assertEqual(Usuario.objects.count(), 4)
        # El historial se conserva.
        self.assertTrue(RegistroBitacora.objects.filter(objeto_id=str(area.pk), accion="area.desactivada").exists())

    def test_area_inactiva_no_se_ofrece_para_nuevos_usuarios(self):
        Area.objects.filter(pk=self.otra_area.pk).update(activa=False)
        respuesta = self.client.get(reverse("configuracion:usuario_nuevo"))
        self.assertNotContains(respuesta, "Laboratorio")


class CoordinadoresTests(BasePanel):
    def test_asignar_coordinador_lo_traslada_y_registra(self):
        url = reverse("configuracion:area_coordinadores", args=[self.otra_area.pk])
        respuesta = self.client.get(url)
        self.assertContains(respuesta, self.coordinador.correo)
        respuesta = self.client.post(url, {"coordinadores": [self.coordinador.pk], "motivo": MOTIVO})
        self.assertRedirects(respuesta, url)
        self.assertEqual(self.recargar(self.coordinador).area, self.otra_area)
        registro = RegistroBitacora.objects.get(accion="usuario.coordinador_asignado")
        self.assertEqual(registro.valor_anterior, {"area": {"id": self.area.pk, "texto": str(self.area)}})
        self.assertEqual(registro.valor_nuevo, {"area": {"id": self.otra_area.pk, "texto": str(self.otra_area)}})
        self.assertEqual(registro.motivo, MOTIVO)

    def test_solo_se_ofrecen_coordinadores_activos(self):
        inactivo = crear_usuario(Rol.COORDINADOR, correo="inactivo@ejemplo.test", area=self.area, activo=False)
        respuesta = self.client.get(reverse("configuracion:area_coordinadores", args=[self.otra_area.pk]))
        self.assertContains(respuesta, self.coordinador.correo)
        self.assertNotContains(respuesta, inactivo.correo)
        self.assertNotContains(respuesta, self.administrador.correo)
        respuesta = self.client.post(
            reverse("configuracion:area_coordinadores", args=[self.otra_area.pk]),
            {"coordinadores": [self.administrador.pk], "motivo": MOTIVO},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(self.recargar(self.administrador).area, None)

    def test_sin_coordinadores_disponibles_muestra_aviso_con_enlace(self):
        respuesta = self.client.get(reverse("configuracion:area_coordinadores", args=[self.area.pk]))
        self.assertContains(respuesta, "No hay coordinadores disponibles")
        self.assertContains(respuesta, f"/configuracion/usuarios/nuevo/?rol=coordinador&amp;area={self.area.pk}")

    def test_enlace_de_crear_usuario_trae_rol_y_area(self):
        respuesta = self.client.get(
            reverse("configuracion:usuario_nuevo"), {"rol": "coordinador", "area": str(self.otra_area.pk)}
        )
        formulario = respuesta.context["formulario"]
        self.assertEqual(formulario.initial["rol"], "coordinador")
        self.assertEqual(formulario.initial["area"], str(self.otra_area.pk))

    def test_no_se_asigna_a_area_inactiva(self):
        Area.objects.filter(pk=self.otra_area.pk).update(activa=False)
        url = reverse("configuracion:area_coordinadores", args=[self.otra_area.pk])
        self.assertContains(self.client.get(url), "El área está inactiva")
        self.client.post(url, {"coordinadores": [self.coordinador.pk], "motivo": MOTIVO})
        self.assertEqual(self.recargar(self.coordinador).area, self.area)

    def test_asignar_exige_motivo(self):
        url = reverse("configuracion:area_coordinadores", args=[self.otra_area.pk])
        respuesta = self.client.post(url, {"coordinadores": [self.coordinador.pk]})
        self.assertContains(respuesta, "Indique el motivo del cambio")
        self.assertEqual(self.recargar(self.coordinador).area, self.area)

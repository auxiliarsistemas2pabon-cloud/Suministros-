from django.urls import reverse

from bitacora.models import RegistroBitacora
from configuracion.tests.base import MOTIVO, BasePanel
from proyecciones.models import ProductoSugerido, UnidadMedida


class UnidadesTests(BasePanel):
    def test_listado_y_filtro(self):
        UnidadMedida.objects.create(nombre="Frasco", abreviatura="fco", activa=False)
        respuesta = self.client.get(reverse("configuracion:unidades"))
        self.assertContains(respuesta, "Caja")
        self.assertContains(respuesta, "Frasco")
        respuesta = self.client.get(reverse("configuracion:unidades"), {"estado": "activos"})
        self.assertNotContains(respuesta, "Frasco")

    def test_crear_editar_y_desactivar(self):
        respuesta = self.client.post(
            reverse("configuracion:unidad_nueva"), {"nombre": "Mililitro", "abreviatura": "ml", "motivo": MOTIVO}
        )
        self.assertRedirects(respuesta, reverse("configuracion:unidades"))
        unidad = UnidadMedida.objects.get(nombre="Mililitro")
        self.assertTrue(RegistroBitacora.objects.filter(accion="unidad.creada", objeto_id=str(unidad.pk)).exists())

        respuesta = self.client.post(
            reverse("configuracion:unidad_editar", args=[unidad.pk]),
            {"nombre": "Mililitros", "abreviatura": "ml", "motivo": MOTIVO},
        )
        self.assertRedirects(respuesta, reverse("configuracion:unidades"))
        self.assertEqual(self.recargar(unidad).nombre, "Mililitros")

        respuesta = self.client.post(reverse("configuracion:unidad_estado", args=[unidad.pk]), {"motivo": MOTIVO})
        self.assertRedirects(respuesta, reverse("configuracion:unidades"))
        self.assertFalse(self.recargar(unidad).activa)
        self.assertTrue(UnidadMedida.objects.filter(pk=unidad.pk).exists())
        self.assertTrue(RegistroBitacora.objects.filter(accion="unidad.desactivada").exists())

    def test_duplicados_sin_distinguir_mayusculas(self):
        respuesta = self.client.post(
            reverse("configuracion:unidad_nueva"), {"nombre": "CAJA", "abreviatura": "CJA", "motivo": MOTIVO}
        )
        self.assertContains(respuesta, "Ya existe una unidad de medida con este nombre.")
        self.assertContains(respuesta, "Ya existe una unidad de medida con esta abreviatura.")
        self.assertEqual(UnidadMedida.objects.count(), 1)

    def test_desactivar_unidad_no_afecta_productos_que_la_usan(self):
        self.client.post(reverse("configuracion:unidad_estado", args=[self.unidad.pk]), {"motivo": MOTIVO})
        producto = self.recargar(self.producto)
        self.assertEqual(producto.unidad_por_defecto, self.unidad)
        self.assertTrue(producto.activo)


class ProductosTests(BasePanel):
    def test_crear_editar_y_desactivar(self):
        otra = UnidadMedida.objects.create(nombre="Unidad", abreviatura="und")
        respuesta = self.client.post(
            reverse("configuracion:producto_nuevo"),
            {"nombre": "Jeringa 5 ml", "unidad_por_defecto": otra.pk, "motivo": MOTIVO},
        )
        self.assertRedirects(respuesta, reverse("configuracion:productos"))
        producto = ProductoSugerido.objects.get(nombre="Jeringa 5 ml")
        self.assertEqual(producto.unidad_por_defecto, otra)
        creado = RegistroBitacora.objects.get(accion="producto.creado")
        self.assertEqual(creado.valor_nuevo["unidad_por_defecto"], {"id": otra.pk, "texto": str(otra)})

        respuesta = self.client.post(
            reverse("configuracion:producto_editar", args=[producto.pk]),
            {"nombre": "Jeringa 5 ml", "unidad_por_defecto": self.unidad.pk, "motivo": MOTIVO},
        )
        self.assertRedirects(respuesta, reverse("configuracion:productos"))
        self.assertEqual(self.recargar(producto).unidad_por_defecto, self.unidad)

        respuesta = self.client.post(reverse("configuracion:producto_estado", args=[producto.pk]), {"motivo": MOTIVO})
        self.assertRedirects(respuesta, reverse("configuracion:productos"))
        self.assertFalse(self.recargar(producto).activo)
        self.assertTrue(ProductoSugerido.objects.filter(pk=producto.pk).exists())

    def test_no_se_puede_elegir_unidad_inactiva(self):
        inactiva = UnidadMedida.objects.create(nombre="Galón", abreviatura="gal", activa=False)
        respuesta = self.client.get(reverse("configuracion:producto_nuevo"))
        self.assertNotContains(respuesta, "Galón")
        respuesta = self.client.post(
            reverse("configuracion:producto_nuevo"),
            {"nombre": "Alcohol", "unidad_por_defecto": inactiva.pk, "motivo": MOTIVO},
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(ProductoSugerido.objects.filter(nombre="Alcohol").exists())

    def test_producto_conserva_su_unidad_aunque_se_haya_desactivado(self):
        UnidadMedida.objects.filter(pk=self.unidad.pk).update(activa=False)
        respuesta = self.client.post(
            reverse("configuracion:producto_editar", args=[self.producto.pk]),
            {"nombre": "Guantes de nitrilo talla M", "unidad_por_defecto": self.unidad.pk, "motivo": MOTIVO},
        )
        self.assertRedirects(respuesta, reverse("configuracion:productos"))
        self.assertEqual(self.recargar(self.producto).nombre, "Guantes de nitrilo talla M")

    def test_sin_unidades_activas_muestra_aviso(self):
        UnidadMedida.objects.update(activa=False)
        self.assertContains(self.client.get(reverse("configuracion:producto_nuevo")), "No hay unidades de medida activas")
        self.assertContains(self.client.get(reverse("configuracion:productos")), "No hay unidades de medida activas")

    def test_nombre_duplicado(self):
        respuesta = self.client.post(
            reverse("configuracion:producto_nuevo"),
            {"nombre": "guantes de NITRILO", "unidad_por_defecto": self.unidad.pk, "motivo": MOTIVO},
        )
        self.assertContains(respuesta, "Ya existe un producto sugerido con este nombre.")

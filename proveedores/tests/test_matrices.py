from datetime import date
from io import BytesIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from cuentas.models import Rol
from cuentas.tests.utilidades import crear_usuario
from proveedores import matrices_servicios as servicios
from proveedores.models import CategoriaProveedor, EvaluacionProveedor, Peso, Requisito, VersionMatriz
from proveedores.servicios import cargar_fr14
from proveedores.tests.utilidades import crear_proveedor


class MatricesTests(TestCase):
    def setUp(self):
        self.admin = crear_usuario(Rol.ADMINISTRADOR)
        self.proveedor = crear_proveedor()
        self.categoria = self.proveedor.categoria or CategoriaProveedor.objects.create(nombre="Categoría ficticia")
        self.version = VersionMatriz.objects.get(numero=1)
        self.req = Requisito.objects.create(numero=1, grupo="calidad", texto="Texto original")
        self.peso = Peso.objects.create(requisito=self.req, categoria=self.categoria, valor=2)
        self.fecha = date(2026, 1, 1)

    def publicar(self, version=None, **datos):
        return servicios.publicar_version(version or self.version, actor=self.admin, motivo="Publicación de prueba", desde=datos.pop("desde", self.fecha), **datos)

    def test_catalogo_inicial_en_borrador_y_unicidad_por_version(self):
        self.assertEqual(self.req.version, self.version)
        nueva = servicios.copiar_version(self.version, actor=self.admin, motivo="Copia")
        self.assertEqual(nueva.requisitos.get(numero=1).texto, self.req.texto)
        self.assertEqual(Peso.objects.filter(requisito__version=nueva).get().valor, 2)

    def test_publicacion_bloquea_modelos_queryset_y_csv(self):
        self.publicar()
        for objeto in (self.req, self.peso):
            with self.assertRaises(ValidationError):
                objeto.save()
            with self.assertRaises(ValidationError):
                objeto.delete()
        with self.assertRaises(ValidationError):
            Requisito.objects.filter(pk=self.req.pk).update(texto="Alterado")
        with self.assertRaises(ValidationError):
            Peso.objects.filter(pk=self.peso.pk).update(valor=1)
        with self.assertRaises(ValidationError):
            cargar_fr14(BytesIO(b"grupo,numero,texto,categoria,peso\ncalidad,1,X,Y,1\n"), actor=self.admin, motivo="Carga")

    def test_sucesora_conserva_evaluacion_textos_y_pesos_originales(self):
        self.publicar()
        ev = servicios.crear_evaluacion(self.proveedor, self.categoria, self.fecha, actor=self.admin, motivo="Evaluar")
        nueva = servicios.copiar_version(self.version, actor=self.admin, motivo="Cambios")
        req = nueva.requisitos.get(numero=1)
        req.texto = "Texto nuevo"
        req.save()
        self.publicar(nueva, desde=date(2026, 2, 1))
        self.version.refresh_from_db()
        self.assertEqual(self.version.hasta, date(2026, 1, 31))
        ev.refresh_from_db()
        self.assertEqual(ev.version, self.version)
        self.assertEqual(ev.version.requisitos.get(numero=1).texto, "Texto original")
        self.assertEqual(servicios.matriz_en_fecha(date(2026, 2, 1)), nueva)
        self.assertEqual(servicios.matriz_en_fecha(self.fecha), self.version)
        with self.assertRaises(ValidationError):
            EvaluacionProveedor.objects.filter(pk=ev.pk).update(version=nueva)

    def test_solapamiento_y_matriz_incompleta_rechazados(self):
        self.publicar(hasta=date(2026, 3, 1))
        nueva = servicios.copiar_version(self.version, actor=self.admin, motivo="Copia")
        with self.assertRaises(ValidationError):
            self.publicar(nueva, desde=date(2026, 2, 1))
        Requisito.objects.create(version=nueva, numero=2, grupo="ambiental", texto="Sin peso")
        with self.assertRaises(ValidationError):
            self.publicar(nueva, desde=date(2026, 4, 1))

    def test_vistas_evaluacion_y_matriz_permisos_y_creacion(self):
        self.publicar()
        ev = servicios.crear_evaluacion(self.proveedor, self.categoria, self.fecha, actor=self.admin, motivo="Evaluación")
        urls = [reverse("proveedores:matrices"), reverse("proveedores:matriz_detalle", args=[self.version.pk]),
                reverse("proveedores:evaluacion_nueva", args=[self.proveedor.pk]), reverse("proveedores:evaluacion_detalle", args=[ev.pk])]
        for rol in (Rol.COORDINADOR, Rol.PROVEEDOR):
            usuario = crear_usuario(rol)
            self.client.force_login(usuario)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
            with self.assertRaises(PermissionDenied):
                servicios.copiar_version(self.version, actor=usuario, motivo="No permitido")
        self.client.logout()
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
        for usuario in (self.admin, crear_usuario(Rol.DESARROLLADOR)):
            self.client.force_login(usuario)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 200)
        respuesta = self.client.post(urls[2], {"categoria": self.categoria.pk, "fecha": self.fecha, "motivo": "Nueva", "accion": "crear"})
        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(EvaluacionProveedor.objects.count(), 2)

    def test_no_hay_evaluacion_sin_version_ni_categoria_aplicable(self):
        with self.assertRaises(ValidationError):
            servicios.crear_evaluacion(self.proveedor, self.categoria, self.fecha, actor=self.admin, motivo="Prueba")
        self.publicar()
        otra = CategoriaProveedor.objects.create(nombre="Sin pesos")
        with self.assertRaises(ValidationError):
            servicios.crear_evaluacion(self.proveedor, otra, self.fecha, actor=self.admin, motivo="Prueba")

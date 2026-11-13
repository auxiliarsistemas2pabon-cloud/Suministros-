from django.test import TestCase

from cuentas.models import Rol, Usuario
from cuentas.tests.utilidades import CLAVE, crear_area, crear_usuario
from proyecciones.models import ProductoSugerido, UnidadMedida

MOTIVO = "Ajuste solicitado por la dirección (caso ficticio)"


class BasePanel(TestCase):
    """Datos ficticios comunes y un administrador con sesión iniciada."""

    def setUp(self):
        self.area = crear_area("Farmacia", "FAR")
        self.otra_area = crear_area("Laboratorio", "LAB")
        self.administrador = crear_usuario(Rol.ADMINISTRADOR, correo="admin@ejemplo.test")
        self.desarrollador = crear_usuario(Rol.DESARROLLADOR, correo="dev@ejemplo.test")
        self.coordinador = crear_usuario(Rol.COORDINADOR, correo="coord@ejemplo.test", area=self.area)
        self.proveedor = crear_usuario(Rol.PROVEEDOR, correo="prov@ejemplo.test")
        self.unidad = UnidadMedida.objects.create(nombre="Caja", abreviatura="cja")
        self.producto = ProductoSugerido.objects.create(nombre="Guantes de nitrilo", unidad_por_defecto=self.unidad)
        self.client.force_login(self.administrador)

    def como(self, usuario):
        self.client.force_login(usuario)

    def recargar(self, objeto):
        objeto.refresh_from_db()
        return objeto


__all__ = ["BasePanel", "CLAVE", "MOTIVO", "Rol", "Usuario", "crear_area", "crear_usuario"]

"""Datos ficticios reutilizables en las pruebas."""

from areas.models import Area
from cuentas.models import Rol, Usuario

CLAVE = "Clave-Ficticia-2026"


def crear_area(nombre="Farmacia", codigo="FAR"):
    return Area.objects.create(nombre=nombre, codigo_area=codigo)


def crear_usuario(rol, correo=None, area=None, **campos):
    if rol == Rol.COORDINADOR and area is None:
        area = Area.objects.first() or crear_area()
    if rol == Rol.PROVEEDOR and "proveedor" not in campos:
        # El rol proveedor exige ficha: se crea una ficticia.
        from proveedores.tests.utilidades import crear_proveedor

        campos["proveedor"] = crear_proveedor()
    return Usuario.objects.create_user(
        correo=correo or f"{rol}@ejemplo.test",
        password=CLAVE,
        nombre=f"Usuario {rol.capitalize()}",
        rol=rol,
        area=area,
        **campos,
    )

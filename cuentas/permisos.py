"""Control de acceso por rol. Toda vista del sistema debe usar rol_requerido."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from cuentas.models import ROLES_ADMIN, Rol


def es_admin(usuario):
    """True si el usuario tiene sesión, está activo y es administrador o desarrollador."""
    return bool(
        usuario is not None
        and getattr(usuario, "is_authenticated", False)
        and getattr(usuario, "is_active", False)
        and getattr(usuario, "rol", None) in ROLES_ADMIN
    )


def rol_requerido(*roles):
    """Permite la vista solo a los roles indicados.

    - Sin sesión: redirige al login (con ?next= a la página pedida).
    - Con sesión pero rol no permitido o usuario inactivo: 403.

    Uso: @rol_requerido(Rol.ADMINISTRADOR, Rol.DESARROLLADOR)
    """
    if not roles:
        raise ValueError("rol_requerido necesita al menos un rol.")
    desconocidos = set(roles) - set(Rol.values)
    if desconocidos:
        raise ValueError(f"Roles desconocidos en rol_requerido: {sorted(desconocidos)}")
    permitidos = frozenset(roles)

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            usuario = request.user
            if not usuario.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not usuario.is_active or getattr(usuario, "rol", None) not in permitidos:
                raise PermissionDenied
            return vista(request, *args, **kwargs)

        envoltura.roles_permitidos = permitidos
        return envoltura

    return decorador

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class ObligarCambioClaveMiddleware:
    """Si el usuario debe cambiar su clave, solo puede usar /cambiar-clave/,
    /salir/ y los archivos estáticos; todo lo demás redirige a cambiar la clave.

    Debe ir después de AuthenticationMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = getattr(request, "user", None)
        if (
            usuario is not None
            and usuario.is_authenticated
            and getattr(usuario, "debe_cambiar_clave", False)
            and not self._ruta_permitida(request.path_info)
        ):
            return redirect("cuentas:cambiar_clave")
        return self.get_response(request)

    @staticmethod
    def _ruta_permitida(ruta):
        permitidas = {reverse("cuentas:cambiar_clave"), reverse("cuentas:salir")}
        if ruta in permitidas:
            return True
        estaticos = "/" + settings.STATIC_URL.lstrip("/")
        return ruta.startswith(estaticos)

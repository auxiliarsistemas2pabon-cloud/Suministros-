from django.contrib import messages
from django.contrib.auth import views as vistas_auth
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator

from cuentas import servicios
from cuentas.forms import FormularioCambioClave, FormularioIngreso
from cuentas.models import Rol
from cuentas.permisos import rol_requerido


class Ingresar(vistas_auth.LoginView):
    template_name = "cuentas/ingresar.html"
    authentication_form = FormularioIngreso
    redirect_authenticated_user = True


class Salir(vistas_auth.LogoutView):
    """Cierra la sesión. Solo acepta POST (protección CSRF); GET responde 405."""


@method_decorator(rol_requerido(*Rol.values), name="dispatch")
class CambiarClave(vistas_auth.PasswordChangeView):
    template_name = "cuentas/cambiar_clave.html"
    form_class = FormularioCambioClave
    success_url = reverse_lazy("inicio")

    def form_valid(self, form):
        servicios.cambiar_clave(self.request, form.user, form.cleaned_data["new_password1"])
        messages.success(self.request, "Su clave se cambió correctamente.")
        return redirect(self.get_success_url())


@rol_requerido(*Rol.values)
def inicio(request):
    if request.user.rol == Rol.PROVEEDOR:
        return redirect("portal:inicio")
    return render(request, "cuentas/inicio.html", {"accesos": servicios.accesos_para(request.user)})

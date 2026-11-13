from django.contrib.admin.apps import AdminConfig


class AdminTecnicoConfig(AdminConfig):
    default_site = "config.admin_sitio.SitioAdminTecnico"

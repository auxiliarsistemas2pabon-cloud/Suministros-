# Calificación ponderada de elegibles · FR-GDS-20

B5 incorpora criterios versionados, escala configurable y una matriz por lista.
Solo Administrador y Desarrollador pueden configurar o calificar. La regla D-07
sigue pendiente de aprobación de la clínica; los valores iniciales son provisionales.

## Preparar los criterios

Abra **Compras → Criterios FR-GDS-20**. La migración crea una versión 1 **en
borrador**, con los criterios del documento de referencia:

| Criterio | Peso |
| --- | --- |
| Administrativos | 30 % |
| Precio | 20 % |
| Valor agregado | 20 % |
| Certificaciones | 30 % |

Puede editar nombres, pesos y notas, agregar filas o marcar Eliminar para omitirlas.
Cada versión admite entre uno y veinte criterios distintos con pesos positivos,
hasta dos decimales y suma exactamente igual a 100 %. Una suma distinta se rechaza
sin guardar cambios parciales.

Guarde antes de publicar. Indique inicio de vigencia y, opcionalmente, fecha final.
Las vigencias publicadas no se superponen. Publicar una sucesora cierra la versión
anterior abierta el día previo a su inicio. Los criterios publicados no se editan;
use **Copiar a borrador**, ajuste los criterios y publique otra vigencia.
La copia, edición, publicación y retiro por sucesión exigen motivo y generan bitácora.

## Elegir escala y método

En **Configuración → Parámetros**, edite **Reglas de cálculo de elegibles
FR-GDS-20 (D-07)**. El valor inicial es:

```json
{"metodo":"directo","escala":["5","3","1"],"pendiente":true}
```

La escala admite entre dos y diez valores distintos entre 0 y 100, hasta tres
decimales y máximo positivo. Escriba los decimales entre comillas; no se admiten
flotantes JSON, valores no finitos ni booleanos como puntajes. El método es
`directo` o `escalado`:

- Directo: cumplimiento × (peso % / 100). Máximo total igual al máximo de la escala,
  inicialmente 5 puntos.
- Escalado: cumplimiento / máximo de la escala × peso %. Máximo total de 100 puntos.

`pendiente=true` muestra el aviso D-07 y el carácter provisional. Cambie a `false`
solo después de obtener aprobación de la clínica. La implementación y sus pruebas
no constituyen aprobación del ejemplo funcional ni de la fórmula oficial.

## Conservar las reglas de cada lista

Al crear una lista, se asigna automáticamente la única versión publicada que cubra
su fecha y se copia el parámetro de escala, método y aprobación pendiente. Estas
reglas permanecen fijas, incluso durante el borrador.

Si no hay versión aplicable, puede registrar la lista y sus participantes, pero
queda sin calificar. En **Calificaciones y puntajes** podrá asignar una versión
después de publicarla. Las listas anteriores a B5 conservan sus datos y siguen este
mismo procedimiento. Solo se asignan reglas una vez y mientras la lista sea borrador.

Publicar otros criterios o cambiar el parámetro afecta a nuevas asignaciones,
sin alterar listas ya configuradas o cerradas. No se reasignan ni recalculan
históricos con parámetros actuales.

## Diligenciar la matriz

Abra una lista y seleccione **Calificaciones y puntajes**. Las filas corresponden
a sus participantes activos; cada criterio muestra peso, cumplimiento, observación
y subtotal. Seleccione valores de la escala guardada, indique motivo y guarde.
Los resultados se calculan en el servidor con Decimal, sin aceptar totales enviados
por el navegador.

Puede guardar respuestas parciales. Una celda **Sin calificar** deja el total
pendiente y muestra el parcial; no equivale a cero. Si la escala contiene cero,
ese valor es una respuesta válida. También se pueden dejar observaciones sin puntaje
o volver a dejar una respuesta pendiente con trazabilidad.

Cada subtotal se redondea a cuatro decimales con ROUND_HALF_UP y el total suma esos
subtotales, para reproducir el resultado mostrado. Mientras está editando, la tabla
identifica los subtotales como los últimos valores guardados; guarde para recalcular.
Si cambian los participantes mientras diligencia, se exige recargar la matriz.

Solo el borrador es editable. Las listas cerradas/anuladas se consultan sin controles
de edición; las mutaciones se rechazan también en servicios y guardado de calificaciones.
Retirar un participante conserva sus respuestas y lo excluye de la matriz activa;
reactivarlo vuelve a mostrar sus calificaciones anteriores.

## Ejemplo reproducible provisional

Con la escala 5/3/1 y los pesos iniciales:

| Criterio | Cumplimiento | Directo | Escalado |
| --- | --- | --- | --- |
| Administrativos, 30 % | 5 | 1,5000 | 30,0000 |
| Precio, 20 % | 3 | 0,6000 | 12,0000 |
| Valor agregado, 20 % | 1 | 0,2000 | 4,0000 |
| Certificaciones, 30 % | 5 | 1,5000 | 30,0000 |
| Total | | **3,8000 / 5** | **76,0000 / 100** |

Estos valores están escritos a mano en las pruebas de `compras/tests_calificacion.py`.
También se comprueban escala configurable, redondeo, permisos, CSRF, auditoría,
atomicidad, unicidad de respuestas, vigencias y conservación de reglas históricas.

La [guía de decisión](decision_elegibles.md) describe B6: cantidades autorizadas,
puestos, desempates, justificaciones y exportación. Los cambios de calificación
invalidan las decisiones y desempates vigentes; deben revisarse. El vínculo
documental se incorporó en [B7](vinculo_documental_elegibles.md) y el cierre en
[B8](cierres_elegibles.md), con foto de resultados y archivo de cada ciclo.

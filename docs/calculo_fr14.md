# Cálculo y conservación de resultados FR-GDS-14 · B1

El detalle de la evaluación muestra puntos, máximo aplicable, porcentaje y
calificación 1/3/5, con desglose por requisito y grupo. Se utilizan los pesos
de la **versión guardada en la evaluación**, incluso si existe una matriz posterior.

## Reglas D-06 pendientes de aprobación

Configuración → Parámetros → `evaluacion.reglas_calculo` contiene un conjunto
coherente de reglas JSON, editable con motivo por administración:

```json
{"si":"1","no":"0","excluir_na":true,"umbral3":"60","umbral5":"80","pendiente":true}
```

- Sí obtiene peso × `si`; No obtiene peso × `no`. Los multiplicadores admiten
  valores entre 0 y 1. Use cadenas decimales entre comillas, sin coma decimal.
- N/A obtiene cero puntos; se excluye del máximo si `excluir_na` es `true`.
  Si se configura `false`, su peso permanece en el máximo.
- Porcentaje = puntos / máximo × 100, con `Decimal` y redondeo a dos decimales
  `ROUND_HALF_UP`. La calificación compara ese porcentaje redondeado con los umbrales:
  5 desde `umbral5`, 3 desde `umbral3`, 1 por debajo de ambos.
- Debe cumplirse 0 ≤ umbral3 < umbral5 ≤ 100. Se valida el conjunto completo
  al editar, evitando una configuración temporal con umbrales incoherentes.
- Los valores iniciales **60 y 80 son provisionales, no oficiales**. La fórmula,
  tratamiento de N/A y umbrales siguen pendientes de aprobación de la clínica.
  La interfaz lo muestra mientras `pendiente` sea `true`. Solo debe cambiarse
  a `false` después de la aprobación correspondiente.

No se presentan estos valores como reglas aprobadas por negocio. La prueba de
«hoja validada» contiene un caso manual provisional (2 puntos de 3, 66,67 %, nota 3)
y debe sustituirse o complementarse cuando la clínica entregue su hoja oficial.

## Finalización

Los borradores muestran un resultado provisional. Se requiere responder todos los
requisitos y un máximo aplicable mayor que cero para finalizar. Con la regla inicial,
si todas las respuestas son N/A, se muestra **No calculable** y se bloquea la finalización.
Las respuestas ausentes nunca permiten finalizar aunque el cálculo parcial tenga máximo.

Al finalizar por POST con motivo se bloquea transaccionalmente la evaluación y se
guarda una foto de puntos, máximo, porcentaje, calificación, desglose y reglas usadas,
con responsable y fecha. No se recalcula esa foto si después cambian parámetros o
matrices. Los resultados con reglas provisionales conservan ese aviso en su foto.

Las respuestas y PDF de una evaluación finalizada quedan en solo lectura. Una
finalización fallida revierte el estado y su resultado. Coordinadores y proveedores
reciben 403; administración y desarrollo tienen acceso.

## Próxima etapa

**B2 ya permite** anular con motivo, copiar evaluaciones y consultar el historial y
la evaluación vigente por proveedor. Consulte [la guía de historial](historial_evaluaciones.md).
La siguiente etapa es B3, sobre documentos exigidos y sus vigencias.

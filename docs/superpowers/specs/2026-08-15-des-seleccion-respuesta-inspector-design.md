# Design: Excepción de des-selección en panel inspector

Fecha: 2026-08-15

## Problema

En el dashboard, hacer clic fuera de la respuesta seleccionada des-selecciona automáticamente. Este
comportamiento se implementa en `DashboardPage.vue` con un listener de clic a nivel de `document`
(`handleOutsideClick`) que des-selecciona cuando el clic cae fuera de la columna de chat
(`chatAreaRef`).

El panel derecho (inspector) contiene dos áreas interactivas — "Embeddings 3D" (rotación/zoom del
gráfico) y "Fuentes usadas" (expandir fragmentos/URLs) — además de un separador arrastrable
(resizer). Cualquier clic en esas áreas des-selecciona la respuesta, lo cual interrumpe la
interacción con el inspector.

## Requerimiento

Conservar la des-selección al hacer clic fuera de la respuesta seleccionada, pero con excepción de
**todo el panel inspector** (columna derecha): los clics en "Embeddings 3D", el resizer y "Fuentes
usadas" NO deben des-seleccionar la respuesta.

## Comportamiento objetivo

| Área de clic | Resultado |
|---|---|
| Fuera de una tarjeta asistente, dentro del área de mensajes del chat | Des-selecciona |
| Fuera del chat (pipeline izquierdo, header, etc.) | Des-selecciona |
| Panel inspector: Embeddings 3D, resizer, Fuentes usadas | NO des-selecciona |

## Diseño

En `frontend/src/components/dashboard/DashboardPage.vue`, modificar `handleOutsideClick` (línea 60)
para que no des-seleccione cuando el objetivo del evento está contenido en la columna inspector,
usando la ref existente `inspectorRef` (ya declarada en la línea 22 y vinculada en la línea 142):

```ts
function handleOutsideClick(e: MouseEvent) {
  const t = e.target as Node
  const isInInspector = inspectorRef.value?.contains(t) ?? false
  if (!chatAreaRef.value?.contains(t) && !isInInspector) {
    dashboardStore.selectResponse(null)
  }
}
```

### Sin cambios

- `ChatWindow.vue` (`handleContainerClick`) se mantiene intacto: clics dentro del área de mensajes
  pero fuera de una tarjeta asistente siguen des-seleccionando.
- Stores (`dashboard.ts`, `chat.ts`) no se modifican.
- Componentes hijos del inspector (`Embeddings3D.vue`, `SourcesList.vue`) no se modifican.

## Criterios de aceptación

1. Seleccionar una respuesta del chat, luego hacer clic en "Embeddings 3D" (rotar/zoom) conserva la
   selección.
2. Seleccionar una respuesta del chat, luego hacer clic en "Fuentes usadas" (expandir una fuente)
   conserva la selección.
3. Seleccionar una respuesta del chat, luego hacer clic en el resizer del inspector conserva la
   selección.
4. Hacer clic fuera de una tarjeta asistente en el área de mensajes des-selecciona.
5. Hacer clic en el panel de pipeline (izquierda) des-selecciona.

## Riesgos y notas

- No hay lógica nueva, solo una condición de guarda. Riesgo de regresión mínimo.
- Se reutiliza `inspectorRef`, que ya cubre toda la columna derecha.

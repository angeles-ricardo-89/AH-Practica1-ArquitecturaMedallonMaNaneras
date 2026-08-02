# Spec UI — Dashboard RAG de mañaneras

## 1. Objetivo de la pantalla

Dashboard de uso mixto para:

- **Desarrollador técnico**: observar estado del pipeline medallón, depurar corridas, revisar RAG, fuentes y embeddings.
- **Evaluador del diplomado**: verificar de forma clara evidencia de cumplimiento por capa.

La pantalla principal debe evitar features adicionales fuera del alcance acordado: **pipeline medallón + chat RAG + fuentes usadas + embeddings 3D**.

---

## 2. Estructura general

Resolución base: **1440 × 900 px**.  
Densidad visual: **media**.  
Tema default: **claro**.  
Estilo: **académico limpio**, con inspiración México/gobierno tratada de forma sobria.

### Layout elegido

**Opción 6 — Inspector derecho con mini-mapa fijo**

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Header técnico global                                                     │
├───────────────┬──────────────────────────────────────────┬────────────────┤
│ Pipeline      │ Chat RAG                                 │ Inspector      │
│ Bronze        │ Historial visible                        │ 3D embeddings  │
│ Silver        │ Respuestas seleccionables                 │ Fuentes usadas │
│ Gold          │ Input de pregunta                         │                │
└───────────────┴──────────────────────────────────────────┴────────────────┘
```

### Medidas base

| Zona | X | Y | W | H |
|---|---:|---:|---:|---:|
| Margen exterior | 24 | 24 | — | — |
| Header técnico | 24 | 24 | 1392 | 64 |
| Main area | 24 | 104 | 1392 | 772 |
| Pipeline izquierdo | 24 | 104 | 300 | 772 |
| Chat central | 344 | 104 | 770 | 772 |
| Inspector derecho | 1134 | 104 | 282 | 772 |
| Gap entre columnas | — | — | 20 | — |

Proporciones aproximadas del main area:

- Pipeline: **22%**
- Chat RAG: **56%**
- Inspector: **20%**
- Gaps: **2%**

> Aunque el objetivo conceptual era 60/25/15, en laptop 1440×900 conviene dar más ancho al inspector para que fuentes y embeddings no queden ilegibles.

---

## 3. Header técnico global

Altura: **64 px**.

Debe mostrar:

- Ambiente actual como texto libre desde backend.
- Versión de la app/dashboard.
- Última corrida global.
- Health global con valores: **Healthy / Degraded / Failed**.
- Botón manual: **Refresh**.
- Indicador: **Auto-refresh 30s**.

No debe traducir ni inferir ambiente. La UI sólo muestra el valor recibido.

### Comportamiento

- Auto-refresh cada **30 segundos**.
- Botón manual de refresh visible.
- Si no hay datos, mostrar **“sin datos”**.

---

## 4. Pipeline medallón

Ubicación: columna izquierda.  
Representación: **timeline vertical Bronze → Silver → Gold**.

### Capas visibles

1. **Bronze**
   - Subtítulo: **Ingesta cruda**

2. **Silver**
   - Subtítulo: **Validación + limpieza**

3. **Gold**
   - Subtítulo: **Embeddings + búsqueda vectorial**

### Datos visibles por tarjeta compacta

Cada tarjeta debe mostrar:

- Status: **En curso / Completo / Falló**
- **Run ID**
- Duración
- Registros agregados
- **Cuarentena / RQL**

### Estados visuales

| Estado | Texto | Color |
|---|---|---|
| En curso | En curso | azul operativo |
| Completo | Completo | verde éxito |
| Falló | Falló | rojo error |

Regla acordada: si una capa falla, **sólo se resalta la tarjeta fallida**. No se dispara alerta global adicional ni se rompe visualmente toda la cadena.

Cuando una capa está en curso, mostrar **sólo texto de estado**, sin spinner, pulso ni barra animada.

### Dependencias

Mostrar dependencia Bronze → Silver → Gold de forma sutil con una línea vertical.  
No saturar con flechas ni diagramas adicionales.

### Click en capa

Al hacer click en Bronze, Silver o Gold se abre **modal de evidencia**.

---

## 5. Modal de evidencia por capa

Contenido:

- Requisitos propios de la capa.
- Métricas de la corrida.
- Enlace a **logs técnicos**.

### Checks propios

#### Bronze

- Fuente pública sin autenticación.
- HTML/raw intacto.
- Timestamp de ingesta.

#### Silver

- Valida registros con contrato Pydantic.
- Separa válidos e inválidos.
- Registra motivo de rechazo.

#### Gold

- Genera embeddings del campo relevante.
- Construye/actualiza índice vectorial.
- Expone búsqueda semántica.

No mostrar checks de otras capas dentro del modal de una capa.

---

## 6. Chat RAG

Ubicación: centro principal.  
Debe conservar **historial visible tipo conversación**.

### Estructura

- Header de módulo: **Chat RAG**.
- Historial de preguntas/respuestas.
- Input inferior para nueva pregunta.
- Botón **Enviar**.

### Respuestas

Cada respuesta se renderiza como una tarjeta seleccionable.  
Selección: **click en toda la tarjeta de respuesta**.

Al seleccionar una respuesta:

- Se actualiza el inspector derecho.
- Se muestran fuentes usadas.
- Se ilumina en el 3D sólo la zona/chunks citados o usados en esa respuesta.

### Métricas visibles como chips

En cada respuesta:

- Similitud.
- Número de fuentes.
- Cobertura de citas.

### Detalle técnico colapsado

Por respuesta, mostrar en sección expandible:

- Reranking.
- Tokens.
- Latency.
- Modelo usado.

---

## 7. Inspector derecho

Ubicación: columna derecha.

### Estado inicial

- Arriba: mini-panel 3D global de embeddings.
- Abajo: estado vacío mínimo para fuentes:
  - **“Selecciona una respuesta del chat para ver fuentes usadas.”**

### Con respuesta seleccionada

Arriba:

- 3D embeddings con chunks citados iluminados.

Abajo:

- Lista de fuentes usadas.

---

## 8. Fuentes usadas

Orden: **por relevancia RAG**, score más alto primero.

Cada fuente debe mostrar visible:

- Fecha completa.
- Título completo.
- Score numérico + badge cualitativo, por ejemplo: **0.87 · Alta**.

Colapsado:

- URL.
- Fragmento usado.

La UI **no calcula** los umbrales Alta / Media / Baja.  
Debe consumir score y etiqueta cualitativa desde backend.

---

## 9. Visualización 3D de embeddings

Unidad visual: cada punto representa un **chunk/fragmento**.

### Estado normal

- Puntos neutros correspondientes al índice Gold.
- Sin color por tema, fecha o conferencia.

### Estado con respuesta seleccionada

- Iluminar sólo los **chunks citados/usados** en la respuesta.
- No iluminar todos los chunks recuperados.
- No hay interacción fuente ↔ embedding.

### Interacción permitida

- Rotar.
- Zoom.

Sin:

- Pan avanzado.
- Filtros.
- Vista expandida.
- Click/hover entre fuente y punto.
- Controles técnicos adicionales.

---

## 10. Idioma y terminología

Base de la UI: español.  
Términos técnicos que pueden permanecer en inglés:

- RAG
- embeddings
- chunks
- logs
- pipeline
- Run ID
- status
- latency
- tokens

Status de capas en español:

- En curso
- Completo
- Falló

Health global en inglés:

- Healthy
- Degraded
- Failed

---

## 11. Reglas de datos

La UI real debe mostrar **sólo datos reales**.

Si el backend no entrega un valor:

- Mostrar **“sin datos”**.
- No inventar números.
- No usar placeholders no marcados.

La imagen de render puede usar valores ficticios realistas sólo para composición visual, pero la implementación real no debe hacerlo.

---

## 12. Paleta estilo Tailwind CSS

### Neutros

| Token | Tailwind-like | Hex | Uso |
|---|---|---:|---|
| `bg` | `stone-50` | `#FAFAF9` | Fondo general |
| `surface` | `white` | `#FFFFFF` | Tarjetas/paneles |
| `surface-muted` | `stone-100` | `#F5F5F4` | Subsuperficies |
| `border` | `stone-200` | `#E7E5E4` | Bordes suaves |
| `border-strong` | `stone-300` | `#D6D3D1` | Bordes destacados |
| `text` | `stone-950` | `#1C1917` | Texto principal |
| `muted` | `stone-500` | `#78716C` | Texto secundario |

### Acentos institucionales sobrios

| Token | Tailwind-like | Hex | Uso |
|---|---|---:|---|
| `primary` | `red-900` | `#7F1D1D` | Acento vino, selección, chunks citados |
| `primary-soft` | `red-50` | `#FEF2F2` | Fondos suaves de acento |
| `secondary` | `green-700` | `#15803D` | Acento verde moderado |
| `secondary-soft` | `green-50` | `#F0FDF4` | Fondos suaves verdes |

### Estados

| Token | Tailwind-like | Hex | Uso |
|---|---|---:|---|
| `status-complete` | `green-600` | `#16A34A` | Completo |
| `status-complete-soft` | `green-100` | `#DCFCE7` | Badge completo |
| `status-running` | `blue-600` | `#2563EB` | En curso |
| `status-running-soft` | `blue-100` | `#DBEAFE` | Badge en curso |
| `status-warning` | `amber-500` | `#F59E0B` | Degraded/Warning |
| `status-warning-soft` | `amber-100` | `#FEF3C7` | Badge warning |
| `status-failed` | `red-600` | `#DC2626` | Falló |
| `status-failed-soft` | `red-100` | `#FEE2E2` | Badge fallo |

### Embeddings

| Token | Hex | Uso |
|---|---:|---|
| `embedding-dot` | `#A8A29E` | Chunks neutros |
| `embedding-active` | `#7F1D1D` | Chunks citados/usados |
| `embedding-axis` | `#D6D3D1` | Ejes sutiles |

---

## 13. Componentes principales

### Card

- Border radius: **16 px**
- Border: `1px solid border`
- Background: `surface`
- Padding: **16–20 px**
- Sin sombras pesadas.
- Se permite sombra muy ligera sólo para modal.

### Badge/chip

- Radius: pill.
- Padding: `4px 8px`.
- Texto: 10–12 px.
- Debe incluir texto, no depender sólo de color.

### Modal

- Width recomendado: **520–640 px**.
- Radius: **18 px**.
- Overlay discreto.
- Debe cerrar con botón visible y tecla Escape.
- No usar modal para fuentes; fuentes viven en el inspector derecho.

---

## 14. Breakpoints recomendados

### Base

- 1440×900: layout 3 columnas completo.

### Laptop compacta / 1366×768

Ajustar:

- Pipeline: 280 px.
- Inspector: 270 px.
- Gaps: 16 px.
- Reducir padding interno de paneles de 20 a 16 px.
- Mantener chat dominante.

### Menor a 1100 px

Recomendación:

- Pipeline arriba como sección colapsable.
- Chat al centro.
- Inspector debajo o como drawer.
- No intentar mantener 3 columnas si las fuentes dejan de ser legibles.

---

## 15. No incluir en este diseño

Para evitar scope creep, no incluir:

- Navegación por fecha/conferencia.
- Filtros por tema.
- Comparador entre administraciones.
- Exportación de reportes.
- Gestión de datasets.
- Vista expandida de embeddings.
- Interacción fuente ↔ punto 3D.
- Placeholders de datos en producción.

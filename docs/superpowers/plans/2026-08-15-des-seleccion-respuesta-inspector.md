# Excepción de des-selección en panel inspector — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que los clics dentro de todo el panel inspector (Embeddings 3D, resizer, Fuentes usadas) no des-seleccionen la respuesta seleccionada en el dashboard, conservando el comportamiento actual de des-selección en el resto.

**Architecture:** Modificar el guard en `handleOutsideClick` de `DashboardPage.vue`, que actualmente des-selecciona cuando el clic cae fuera de `chatAreaRef`, para que además salte cuando el clic cae dentro de `inspectorRef`. La ref `inspectorRef` ya existe y cubre toda la columna derecha. Ningún componente hijo ni store cambia.

**Tech Stack:** Vue 3 + TypeScript + Vitest + @vue/test-utils + happy-dom (frontend/).

**Spec:** `docs/superpowers/specs/2026-08-15-des-seleccion-respuesta-inspector-design.md`

---

### Task 1: Excepción del panel inspector en `handleOutsideClick`

**Files:**
- Modify: `frontend/src/components/dashboard/DashboardPage.vue:60-64`
- Test: `frontend/tests/components/DashboardPage.test.ts`

- [ ] **Step 1: Agregar tests que fijen el comportamiento nuevo**

Añadir al final del `describe('DashboardPage Integration', ...)` en
`frontend/tests/components/DashboardPage.test.ts` el helper y los dos tests siguientes:

```ts
  async function mountWithSelectedResponse() {
    const chatStore = useChatStore()
    chatStore.messages = [
      {
        id: 'msg_user_1',
        role: 'user',
        content: 'Pregunta de prueba',
        timestamp: Date.now(),
      },
      {
        id: 'msg_assistant_1',
        role: 'assistant',
        content: 'Respuesta con fuentes',
        timestamp: Date.now(),
        sources: [
          {
            conference_id: 'conf_001',
            conference_date: '2026-07-30',
            participant: 'Presidenta',
            chunk_text: 'Fragmento sobre vivienda',
            similarity: 0.87,
            conference_url: 'https://gob.mx',
            pregunta_activa: 'Conferencia de prensa del 30 de julio de 2026',
            qualitative_label: 'Alta',
            embedding_3d: [1, 2, 3],
          },
        ],
        metrics: {
          similarity: 0.87,
          numSources: 1,
          coverage: 100,
          latency: 1200,
          tokens: 800,
          model: 'test-model',
        },
      },
    ]

    const wrapper = mount(DashboardPage)
    await nextTick()

    const dashboardStore = useDashboardStore()
    dashboardStore.selectResponse('msg_assistant_1')
    await nextTick()
    expect(dashboardStore.selectedResponseId).toBe('msg_assistant_1')

    return { wrapper, dashboardStore }
  }

  it('keeps selection when clicking inside the inspector column', async () => {
    const { wrapper, dashboardStore } = await mountWithSelectedResponse()

    const embeddingsHeading = wrapper
      .findAll('h3')
      .find((h) => h.text().includes('Embeddings 3D'))
    expect(embeddingsHeading).toBeTruthy()
    await embeddingsHeading!.trigger('click')
    await nextTick()
    expect(dashboardStore.selectedResponseId).toBe('msg_assistant_1')

    const resizer = wrapper.find('.cursor-ns-resize')
    expect(resizer.exists()).toBe(true)
    await resizer.trigger('click')
    await nextTick()
    expect(dashboardStore.selectedResponseId).toBe('msg_assistant_1')

    const sourceCard = wrapper.find('.rounded-xl')
    expect(sourceCard.exists()).toBe(true)
    await sourceCard.trigger('click')
    await nextTick()
    expect(dashboardStore.selectedResponseId).toBe('msg_assistant_1')
  })

  it('deselects when clicking outside chat and inspector', async () => {
    const { dashboardStore } = await mountWithSelectedResponse()

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()

    expect(dashboardStore.selectedResponseId).toBeNull()
  })
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `pnpm test:unit -- DashboardPage.test.ts`
Expected: `keeps selection when clicking inside the inspector column` FAIL (la selección se
pierde) y `deselects when clicking outside chat and inspector` puede pasar o fallar, pero al
menos el test de "keeps selection" debe fallar.

- [ ] **Step 3: Implementar el cambio en `DashboardPage.vue`**

Reemplazar `handleOutsideClick` (líneas 60-64) por:

```ts
function handleOutsideClick(e: MouseEvent) {
  const t = e.target as Node
  const isInInspector = inspectorRef.value?.contains(t) ?? false
  if (!chatAreaRef.value?.contains(t) && !isInInspector) {
    dashboardStore.selectResponse(null)
  }
}
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `pnpm test:unit -- DashboardPage.test.ts`
Expected: todos los tests PASS, incluidos `keeps selection when clicking inside the inspector
column` y `deselects when clicking outside chat and inspector`.

- [ ] **Step 5: Lint y typecheck**

```bash
pnpm lint
pnpm typecheck
```

Expected: sin errores.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard/DashboardPage.vue frontend/tests/components/DashboardPage.test.ts
git commit -m "no deselecciona respuesta al hacer clic en panel inspector"
```

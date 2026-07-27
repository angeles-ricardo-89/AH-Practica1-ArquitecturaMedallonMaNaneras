import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SemaforoEstado from '../../src/components/dashboard/SemaforoEstado.vue'

describe('SemaforoEstado', () => {
  it('shows green dot for ok status', () => {
    const wrapper = mount(SemaforoEstado, {
      props: { status: 'ok' },
    })
    expect(wrapper.find('.bg-green-500').exists()).toBe(true)
    expect(wrapper.text()).toContain('OK')
  })

  it('shows yellow dot for running status', () => {
    const wrapper = mount(SemaforoEstado, {
      props: { status: 'running' },
    })
    expect(wrapper.find('.bg-yellow-500').exists()).toBe(true)
    expect(wrapper.text()).toContain('Ejecutando')
  })

  it('shows red dot for error status', () => {
    const wrapper = mount(SemaforoEstado, {
      props: { status: 'error' },
    })
    expect(wrapper.find('.bg-red-500').exists()).toBe(true)
    expect(wrapper.text()).toContain('Error')
  })

  it('shows gray dot for unknown status', () => {
    const wrapper = mount(SemaforoEstado, {
      props: { status: 'unknown' },
    })
    expect(wrapper.find('.bg-gray-400').exists()).toBe(true)
    expect(wrapper.text()).toContain('Desconocido')
  })

  it('displays custom label when provided', () => {
    const wrapper = mount(SemaforoEstado, {
      props: { status: 'ok', label: 'Todo bien' },
    })
    expect(wrapper.text()).toContain('Todo bien')
  })
})

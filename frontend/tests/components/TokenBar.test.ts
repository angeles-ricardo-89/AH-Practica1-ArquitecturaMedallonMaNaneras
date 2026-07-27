import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TokenBar from '../../src/components/chat/TokenBar.vue'

describe('TokenBar', () => {
  it('renders token count and max', () => {
    const wrapper = mount(TokenBar, {
      props: { used: 100, max: 1000 },
    })
    expect(wrapper.text()).toContain('100')
    expect(wrapper.text()).toContain('1000')
  })

  it('shows green bar below 70%', () => {
    const wrapper = mount(TokenBar, {
      props: { used: 500, max: 1000 },
    })
    expect(wrapper.find('.bg-green-500').exists()).toBe(true)
  })

  it('shows yellow bar between 70% and 90%', () => {
    const wrapper = mount(TokenBar, {
      props: { used: 800, max: 1000 },
    })
    expect(wrapper.find('.bg-yellow-500').exists()).toBe(true)
  })

  it('shows red bar at 90% or above', () => {
    const wrapper = mount(TokenBar, {
      props: { used: 900, max: 1000 },
    })
    expect(wrapper.find('.bg-red-500').exists()).toBe(true)
  })

  it('caps width at 100%', () => {
    const wrapper = mount(TokenBar, {
      props: { used: 2000, max: 1000 },
    })
    const bar = wrapper.find('.bg-red-500')
    expect(bar.attributes('style')).toContain('width: 100%')
  })

  it('does not render when used is 0', () => {
    const wrapper = mount(TokenBar, {
      props: { used: 0, max: 1000 },
    })
    expect(wrapper.find('.w-full').exists()).toBe(false)
  })
})

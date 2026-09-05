import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '../../src/utils/markdown'

describe('renderMarkdown', () => {
  it('renders markdown to HTML', () => {
    const out = renderMarkdown('**negrita** y _cursiva_')
    expect(out).toContain('<strong>negrita</strong>')
    expect(out).toContain('<em>cursiva</em>')
  })

  it('strips script tags', () => {
    const out = renderMarkdown('<script>/* sin ejecutable */</script><p>ok</p>')
    expect(out).not.toContain('<script>')
  })

  it('strips img onerror handlers', () => {
    const out = renderMarkdown('<img src="x" onerror="alert(1)">')
    expect(out).not.toContain('onerror')
  })
})

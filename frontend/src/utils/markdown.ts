import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({
  gfm: true,
  breaks: true,
  headerIds: false,
  mangle: false,
})

const SCHEME_PREFIX = /^[a-zA-Z][a-zA-Z0-9+.-]*:/
const SAFE_SCHEMES = /^(?:https?|ftp|mailto|tel|callto|sms|cid|xmpp|matrix):/i
const DATA_IMAGE = /^data:image\//i

function collapseUrl(value: string): string {
  let out = ''
  for (const ch of value) {
    const code = ch.charCodeAt(0)
    if (code > 0x20 && code !== 0x7f) out += ch
  }
  return out
}

function isSafeUrl(value: string): boolean {
  const collapsed = collapseUrl(value)
  return !SCHEME_PREFIX.test(collapsed) || SAFE_SCHEMES.test(collapsed)
}

function isSafeImageUrl(value: string): boolean {
  const collapsed = collapseUrl(value)
  return isSafeUrl(collapsed) || DATA_IMAGE.test(collapsed)
}

marked.use({
  renderer: {
    link({ href, tokens }: marked.Tokens.Link) {
      if (!isSafeUrl(href)) {
        return this.parser.parseInline(tokens)
      }
      return false
    },
    image({ href, text, tokens }: marked.Tokens.Image) {
      if (!isSafeImageUrl(href)) {
        return tokens
          ? this.parser.parseInline(tokens, this.parser.textRenderer)
          : text
      }
      return false
    },
  },
})

export function renderMarkdown(text: string): string {
  const raw = marked.parse(text, { async: false }) as string
  return DOMPurify.sanitize(raw)
}

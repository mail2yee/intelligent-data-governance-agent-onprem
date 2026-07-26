import { describe, expect, it } from 'vitest'
import { I18N, makeT } from './i18n'

describe('I18N', () => {
  it('zh and en have exactly the same set of keys (no translation drift)', () => {
    const zhKeys = Object.keys(I18N.zh).sort()
    const enKeys = Object.keys(I18N.en).sort()
    expect(enKeys).toEqual(zhKeys)
  })

  it('every value is either a non-empty string or a function', () => {
    for (const lang of ['zh', 'en']) {
      for (const [key, value] of Object.entries(I18N[lang])) {
        const isValid = typeof value === 'function' || (typeof value === 'string' && value.length > 0)
        expect(isValid, `${lang}.${key} should be a non-empty string or function`).toBe(true)
      }
    }
  })
})

describe('makeT', () => {
  it('looks up the requested language', () => {
    const t = makeT('en')
    expect(t('searchBtn')).toBe('Search')
  })

  it('function-valued translations still work through t()', () => {
    const t = makeT('zh')
    expect(t('resultsMeta')(3)).toBe('為你找到 3 個相關 Data Subject')
  })
})

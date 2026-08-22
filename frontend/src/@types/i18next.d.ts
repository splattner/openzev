// When migrating the last dynamic/computed key patterns, enable strict
// resource typing by importing en and setting resources below:
//   import type { en } from '../i18n/locales/en'

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation'
    // resources: {
    //   translation: typeof en
    // }
  }
}

export {}

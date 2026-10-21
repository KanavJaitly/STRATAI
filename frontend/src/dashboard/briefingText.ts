// P9-M5: why the briefing was served in its fixed layout, in plain words. The served reason code is always shown
// beside it, so an unknown code is kept verbatim rather than guessed at.
const FALLBACK_TEXT: Record<string, string> = {
  disabled: 'the language model is switched off',
  egress_not_approved: 'sending report data to the language-model provider is not approved',
  no_credential: 'no language-model credential is configured',
  sdk_unavailable: 'the language-model SDK is not installed',
  refusal: 'the language model declined the request',
  truncated: "the language model's output was cut off",
  no_text: 'the language model returned no text',
  invalid_json: "the language model's output was not valid JSON",
}

export function fallbackText(reason: string | null): string {
  if (reason === null) return ''
  if (reason.startsWith('api_error:')) return `the language-model call failed (${reason.slice('api_error:'.length)})`
  if (reason.startsWith('validation_failed:')) {
    return `the language model's arrangement failed a check (${reason.slice('validation_failed:'.length)})`
  }
  return Object.hasOwn(FALLBACK_TEXT, reason) ? FALLBACK_TEXT[reason] : reason
}

/** Whether a language model was called before the fixed layout was served (it was, unless a gate stopped it). */
export function modelWasCalled(reason: string | null): boolean {
  return reason !== null && !['disabled', 'egress_not_approved', 'no_credential', 'sdk_unavailable'].includes(reason)
}

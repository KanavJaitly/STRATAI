// Client-side checks on a manual PDF before upload, and on a ruleset's carried-over markers. The server checks
// everything again; these only give an earlier, clearer message.

export const MAX_MANUAL_BYTES = 100 * 1024 * 1024 // the server's limit (data/human_inputs.py)

export async function checkManualFile(file: File): Promise<string | null> {
  if (!file.size) return 'The file is empty.'
  if (file.size > MAX_MANUAL_BYTES) return `The file is ${(file.size / 1048576).toFixed(1)} MB; the limit is 100 MB.`
  if (!(file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'))) return 'Choose a PDF file.'
  const head = new Uint8Array(await file.slice(0, 5).arrayBuffer())
  if (String.fromCharCode(...head) !== '%PDF-') return 'This is not a PDF (it does not start with %PDF-).'
  return null
}

/** The marker data/ruleset_worksheet.py puts on carried-over text; approval refuses while any remains. */
export const UNVERIFIED = 'UNVERIFIED (carried from'

export function countMarkers(text: string): number {
  return text.split(UNVERIFIED).length - 1
}

// A SYNTHETIC PDF for the live upload test (port of tests/pdf_fixtures.py): valid multi-page PDF with real text.
// It is not a game manual and is never evidence.

const PAGES = [
  '2099 FIRST Robotics Competition SYNTHETICA\nGame Manual\nRevision 1.0\nJanuary 6, 2099',
  '5 ARENA\n5.1 Overview\nThe ARENA includes the FIELD and the scoring elements.',
  '6 MATCH Play\n6.1 Match periods\nThe AUTO period lasts 15 seconds.\nThe TELEOP period lasts 2 minutes and 15 seconds.',
  '6.2 Scoring\nCORAL in the trough: 3 points\nALGAE in the net: 4 points\nLEAVE: 2 points',
  '6.3 Ranking Points\nA team earns 3 Ranking Points for a win.',
  '11 Tournaments\n11.1 Alliance Selection\nEight (8) ALLIANCES are formed in Alliance Selection.\n11.2 Playoffs\n'
    + 'The playoff tournament is double-elimination with Finals best-of-three.',
]

function escape(text: string): string {
  return text.replaceAll('\\', '\\\\').replaceAll('(', '\\(').replaceAll(')', '\\)')
}

export function syntheticManualPdf(pages: string[] = PAGES): Uint8Array {
  const objects: string[] = []
  const pageIds = pages.map((_, i) => 4 + 2 * i)
  objects.push('<< /Type /Catalog /Pages 2 0 R >>')
  objects.push(`<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${pages.length} >>`)
  objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
  pages.forEach((text, i) => {
    const stream = 'BT /F1 11 Tf 14 TL 50 760 Td ' + text.split('\n').map((l) => `(${escape(l)}) Tj T*`).join(' ') + ' ET'
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${pageIds[i] + 1} 0 R >>`)
    objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`)
  })
  let out = '%PDF-1.7\n'
  const offsets: number[] = []
  objects.forEach((body, i) => {
    offsets.push(out.length)
    out += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xref = out.length
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  for (const offset of offsets) out += `${String(offset).padStart(10, '0')} 00000 n \n`
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return new TextEncoder().encode(out)
}

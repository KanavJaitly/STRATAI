import { Link } from 'react-router-dom'

import { PageHeader } from '../common'

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <p>There is no page at this address. <Link to="/">Go to the events list</Link>.</p>
    </>
  )
}

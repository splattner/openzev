import { Link } from 'react-router-dom'

export function NotFoundPage() {
    return (
        <div className="center-screen">
            <div className="card not-found-card">
                <h2>Page not found</h2>
                <p className="muted">The route you requested does not exist.</p>
                <Link className="button" to="/">Back to dashboard</Link>
            </div>
        </div>
    )
}

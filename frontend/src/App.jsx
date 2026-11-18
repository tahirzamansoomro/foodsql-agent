
import { useCallback, useEffect, useState } from 'react'
import './App.css'

const API_BASE_URL = 'http://localhost:8000'

function App() {
  const [analytics, setAnalytics] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [lastUpdated, setLastUpdated] = useState(null)

  const [question, setQuestion] = useState('')
  const [agentLoading, setAgentLoading] = useState(false)
  const [agentError, setAgentError] = useState('')
  const [agentResult, setAgentResult] = useState(null)

  const fetchAnalytics = useCallback(async () => {
    try {
      setLoading(true)
      setError('')

      const response = await fetch(`${API_BASE_URL}/analytics/summary`)
      if (!response.ok) throw new Error(`API request failed: ${response.status}`)

      const data = await response.json()
      setAnalytics(data)
      setLastUpdated(new Date())
    } catch (err) {
      setError(err.message || 'Unable to connect to API')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAnalytics()
    const refreshInterval = setInterval(fetchAnalytics, 10000)
    return () => clearInterval(refreshInterval)
  }, [fetchAnalytics])

  const askAgent = async (event) => {
    event.preventDefault()
    if (!question.trim() || agentLoading) return

    setAgentLoading(true)
    setAgentError('')
    setAgentResult(null)

    try {
      const response = await fetch(`${API_BASE_URL}/agent/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.trim() }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || `Request failed: ${response.status}`)
      }

      setAgentResult(data)
    } catch (err) {
      setAgentError(err.message || 'Unable to process your question')
    } finally {
      setAgentLoading(false)
    }
  }

  const formatCurrency = (amount) =>
    new Intl.NumberFormat('en-PK', {
      style: 'currency',
      currency: 'PKR',
      maximumFractionDigits: 0,
    }).format(amount ?? 0)

  const formatDate = (value) => {
    if (!value) return 'Not available'
    return new Date(value).toLocaleString('en-PK', {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  }

  return (
    <div className="dashboard">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">FS</div>
          <div>
            <h2>FoodSQL-Agent</h2>
            <span>Analytics Platform</span>
          </div>
        </div>

        <nav className="navigation">
          <p className="nav-label">WORKSPACE</p>
          <a className="nav-link active" href="#overview">
            <span>▦</span> Overview
          </a>
          <a className="nav-link" href="#orders">
            <span>◷</span> Order Analytics
          </a>
          <a className="nav-link" href="#ai-assistant">
            <span>✧</span> AI SQL Assistant
          </a>
        </nav>

        <div className="sidebar-footer">
          <span className="status-dot"></span>
          Local Development
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <span className="breadcrumb">Workspace / Overview</span>
            <h1>Analytics Dashboard</h1>
          </div>

          <button
            className="refresh-button"
            onClick={fetchAnalytics}
            disabled={loading}
          >
            ↻ {loading ? 'Loading...' : 'Refresh Data'}
          </button>
        </header>

        <section className="welcome-section" id="overview">
          <div>
            <p className="eyebrow">FOOD DELIVERY INTELLIGENCE</p>
            <h2>Streaming Analytics Overview</h2>
            <p>
              Monitor your simulated food-delivery order activity
              and business performance.
            </p>
          </div>

          <div className="api-indicator">
            <span className={`status-dot ${error ? 'offline' : ''}`}></span>
            {error ? 'API Disconnected' : 'API Connection'}
          </div>
        </section>

        {error && (
          <div className="error-message">
            <strong>Connection Error:</strong> {error}
            <button onClick={fetchAnalytics}>Retry</button>
          </div>
        )}

        <section className="metrics-grid">
          <article className="metric-card">
            <div className="metric-heading">
              <span>Total Orders</span>
              <span className="metric-icon purple">▦</span>
            </div>
            <h3>
              {loading && !analytics
                ? '...'
                : (analytics?.total_orders ?? 0).toLocaleString()}
            </h3>
            <p>Orders received</p>
          </article>

          <article className="metric-card">
            <div className="metric-heading">
              <span>Total Revenue</span>
              <span className="metric-icon green">₨</span>
            </div>
            <h3>
              {loading && !analytics
                ? '...'
                : formatCurrency(analytics?.total_revenue)}
            </h3>
            <p>Simulated order revenue</p>
          </article>

          <article className="metric-card">
            <div className="metric-heading">
              <span>Average Order Value</span>
              <span className="metric-icon orange">◈</span>
            </div>
            <h3>
              {loading && !analytics
                ? '...'
                : formatCurrency(analytics?.average_order_value)}
            </h3>
            <p>Average revenue per order</p>
          </article>

          <article className="metric-card">
            <div className="metric-heading">
              <span>Order Status</span>
              <span className="metric-icon blue">✓</span>
            </div>
            <h3>
              {loading && !analytics
                ? '...'
                : analytics?.order_status?.length ?? 0}
            </h3>
            <p>Distinct order statuses</p>
          </article>
        </section>

        <section className="content-grid" id="orders">
          <article className="panel status-panel">
            <div className="panel-header">
              <div>
                <h3>Order Status Summary</h3>
                <p>Distribution of received orders</p>
              </div>
              <span className="panel-badge">Analytics</span>
            </div>

            {loading && !analytics ? (
              <p className="empty-state">Loading analytics...</p>
            ) : analytics?.order_status?.length > 0 ? (
              <div className="status-list">
                {analytics.order_status.map((item) => {
                  const percentage = analytics.total_orders
                    ? (item.count / analytics.total_orders) * 100
                    : 0

                  return (
                    <div className="status-item" key={item.status}>
                      <div className="status-item-heading">
                        <span>{item.status}</span>
                        <strong>{item.count} orders</strong>
                      </div>
                      <div className="progress-track">
                        <div
                          className="progress-fill"
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                      <small>{percentage.toFixed(1)}% of total orders</small>
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="empty-state">No order data available.</p>
            )}
          </article>

          <article className="panel activity-panel">
            <div className="panel-header">
              <div>
                <h3>System Information</h3>
                <p>Backend and data connection</p>
              </div>
            </div>

            <div className="info-row">
              <span>Backend API</span>
              <strong>{error ? 'Disconnected' : 'FoodSQL API'}</strong>
            </div>
            <div className="info-row">
              <span>Database</span>
              <strong>DuckDB</strong>
            </div>
            <div className="info-row">
              <span>Streaming Source</span>
              <strong>Simulated Events</strong>
            </div>
            <div className="info-row">
              <span>Latest Order</span>
              <strong className="date-value">
                {formatDate(analytics?.latest_order_time)}
              </strong>
            </div>
            <div className="info-row">
              <span>Last Dashboard Update</span>
              <strong className="date-value">
                {lastUpdated ? lastUpdated.toLocaleTimeString() : 'Pending'}
              </strong>
            </div>
          </article>
        </section>

        <section className="panel ai-panel" id="ai-assistant">
          <div className="panel-header">
            <div>
              <p className="eyebrow">AI-POWERED DATA ANALYSIS</p>
              <h3>✧ FoodSQL-Agent Assistant</h3>
              <p>
                Ask questions in natural language and generate SQL automatically.
              </p>
            </div>
            <span className="panel-badge">Gemini AI</span>
          </div>

          <form className="ai-form" onSubmit={askAgent}>
            <label htmlFor="agent-question">Ask your data a question</label>
            <textarea
              id="agent-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Example: How many orders are there for each restaurant?"
              rows={3}
              disabled={agentLoading}
            />
            <div className="ai-form-footer">
              <span>Use English questions about the available database tables.</span>
              <button
                className="ask-button"
                type="submit"
                disabled={agentLoading || !question.trim()}
              >
                {agentLoading ? 'Analyzing...' : '✧ Ask FoodSQL-Agent'}
              </button>
            </div>
          </form>

          <div className="suggested-questions">
            <span>Try asking:</span>
            {[
              'How many orders are there?',
              'Show the top 5 restaurants by order count.',
              'What is the average order amount?',
            ].map((item) => (
              <button
                type="button"
                key={item}
                onClick={() => setQuestion(item)}
                disabled={agentLoading}
              >
                {item}
              </button>
            ))}
          </div>

          {agentLoading && (
            <div className="agent-message">
              <span className="agent-spinner"></span>
              Gemini is generating and validating your SQL query...
            </div>
          )}

          {agentError && (
            <div className="error-message agent-error">
              <strong>Agent Error:</strong> {agentError}
            </div>
          )}

          {agentResult && (
            <div className="agent-result">
              <div className="result-heading">
                <h4>Query Result</h4>
                <span
                  className={
                    agentResult.success ? 'result-success' : 'result-failed'
                  }
                >
                  {agentResult.success ? 'Successful' : 'Unsuccessful'}
                </span>
              </div>

              <div className="result-meta">
                <span>Model: {agentResult.model || 'Gemini'}</span>
                <span>Attempts: {agentResult.attempts ?? 'N/A'}</span>
                <span>
                  Model Latency:{' '}
                  {agentResult.latency_ms != null
                    ? `${Number(agentResult.latency_ms).toFixed(0)} ms`
                    : 'N/A'}
                </span>
                <span>
                  Total Query Time:{' '}
                  {agentResult.total_latency_ms != null
                    ? `${Number(agentResult.total_latency_ms).toFixed(0)} ms`
                    : 'N/A'}
                </span>
              </div>

              {agentResult.sql && (
                <div className="sql-output">
                  <div className="output-label">GENERATED SQL</div>
                  <pre>
                    <code>{agentResult.sql}</code>
                  </pre>
                </div>
              )}

              {agentResult.error && (
                <p className="agent-error-text">{agentResult.error}</p>
              )}

              {agentResult.columns && agentResult.rows && (
                <div className="query-table-wrapper">
                  <div className="output-label">QUERY DATA</div>
                  {agentResult.rows.length ? (
                    <table className="query-table">
                      <thead>
                        <tr>
                          {agentResult.columns.map((column) => (
                            <th key={column}>{column}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {agentResult.rows.map((row, index) => (
                          <tr key={index}>
                            {agentResult.columns.map((column) => (
                              <td key={column}>
                                {String(row[column] ?? '')}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="empty-state">Query returned no rows.</p>
                  )}
                  {agentResult.truncated && (
                    <p className="table-note">Showing the first 100 rows.</p>
                  )}
                </div>
              )}

              {agentResult.trace?.length > 0 && (
                <details className="agent-trace">
                  <summary>View agent execution trace</summary>
                  <pre>{JSON.stringify(agentResult.trace, null, 2)}</pre>
                </details>
              )}
            </div>
          )}
        </section>

        <footer className="dashboard-footer">
          <span>FoodSQL-Agent · Final Year Project</span>
          <span>Streaming Analytics & AI Text-to-SQL</span>
        </footer>
      </main>
    </div>
  )
}

export default App

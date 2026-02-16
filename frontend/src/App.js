import React, { useState, useEffect, useCallback } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
} from "recharts";
import "./App.css";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:5001";

/* ---------- Formatting helpers ---------- */
const fmtCurrency = (val) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(val);

const fmtPct = (val) =>
  val == null ? "—" : `${val > 0 ? "+" : ""}${val.toFixed(1)}%`;

/* ---------- KPI Card ---------- */
function KpiCard({ label, value, subValue, trend }) {
  const trendColor =
    trend == null ? "#8a8f98" : trend >= 0 ? "#34d399" : "#f87171";

  return (
    <div className="kpi-card">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {subValue != null && (
        <span className="kpi-sub" style={{ color: trendColor }}>
          {subValue}
        </span>
      )}
    </div>
  );
}

/* ---------- Custom Tooltip ---------- */
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="chart-tooltip">
      <p className="tooltip-month">{d.month}</p>
      <p className="tooltip-mrr">{fmtCurrency(d.mrr_amount)}</p>
      <p className="tooltip-detail">
        {d.active_subscriptions} subs &middot; {d.active_customers} customers
      </p>
    </div>
  );
}

/* ---------- Main App ---------- */
export default function App() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${API_BASE}/api/mrr`);
      if (!res.ok) throw new Error(`API returned ${res.status}`);
      const json = await res.json();
      if (json.status === "error") throw new Error(json.error);
      setData(json.data);
      setError(null);
    } catch (err) {
      console.error("Fetch error:", err);
      setError(err.message);
      // Load demo data for development / screenshot purposes
      setData(getDemoData());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Computed KPIs
  const latest = data[data.length - 1];
  const prev = data[data.length - 2];
  const first = data[0];
  const mrrChange =
    latest && prev ? ((latest.mrr_amount - prev.mrr_amount) / prev.mrr_amount) * 100 : null;
  const totalGrowth =
    latest && first && first.mrr_amount > 0
      ? ((latest.mrr_amount - first.mrr_amount) / first.mrr_amount) * 100
      : null;

  return (
    <div className="app">
      <header className="header">
        <div className="header-left">
          <div className="logo">
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
              <rect width="28" height="28" rx="7" fill="#6366f1" />
              <path
                d="M7 19V12l4 3 3-6 4 4 3-5v11H7z"
                fill="white"
                opacity="0.9"
              />
            </svg>
            <h1>MRR Dashboard</h1>
          </div>
          <span className="header-sub">Monthly Recurring Revenue</span>
        </div>
        <div className="header-right">
          <span className="badge">Stripe + BigQuery</span>
          <span className="last-updated">
            {data.length > 0 ? `${data.length} months loaded` : ""}
          </span>
        </div>
      </header>

      {/* KPI Row */}
      <div className="kpi-row">
        <KpiCard
          label="Current MRR"
          value={latest ? fmtCurrency(latest.mrr_amount) : "—"}
          subValue={mrrChange != null ? fmtPct(mrrChange) + " MoM" : null}
          trend={mrrChange}
        />
        <KpiCard
          label="Active Subscriptions"
          value={latest ? latest.active_subscriptions : "—"}
          subValue={
            latest && prev
              ? `${latest.active_subscriptions - prev.active_subscriptions >= 0 ? "+" : ""}${latest.active_subscriptions - prev.active_subscriptions} from last month`
              : null
          }
          trend={latest && prev ? latest.active_subscriptions - prev.active_subscriptions : null}
        />
        <KpiCard
          label="Active Customers"
          value={latest ? latest.active_customers : "—"}
        />
        <KpiCard
          label="Total Growth"
          value={totalGrowth != null ? fmtPct(totalGrowth) : "—"}
          subValue={first ? `from ${fmtCurrency(first.mrr_amount)}` : null}
          trend={totalGrowth}
        />
      </div>

      {/* Chart */}
      <div className="chart-container">
        <div className="chart-header">
          <h2>MRR Trend</h2>
          <span className="chart-range">
            {data.length > 0
              ? `${data[0].month} — ${data[data.length - 1].month}`
              : ""}
          </span>
        </div>
        {loading ? (
          <div className="chart-loading">Loading...</div>
        ) : (
          <ResponsiveContainer width="100%" height={380}>
            <AreaChart data={data} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
              <defs>
                <linearGradient id="mrrGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366f1" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e4e9" vertical={false} />
              <XAxis
                dataKey="month"
                tick={{ fill: "#6b7280", fontSize: 13 }}
                axisLine={{ stroke: "#e2e4e9" }}
                tickLine={false}
                dy={8}
              />
              <YAxis
                tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                tick={{ fill: "#6b7280", fontSize: 13 }}
                axisLine={false}
                tickLine={false}
                dx={-4}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="mrr_amount"
                stroke="#6366f1"
                strokeWidth={2.5}
                fill="url(#mrrGradient)"
                dot={{ r: 5, fill: "#6366f1", strokeWidth: 2, stroke: "#fff" }}
                activeDot={{ r: 7, fill: "#6366f1", stroke: "#fff", strokeWidth: 3 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Data Table */}
      {data.length > 0 && (
        <div className="table-container">
          <h2>Monthly Breakdown</h2>
          <table>
            <thead>
              <tr>
                <th>Month</th>
                <th className="num">MRR</th>
                <th className="num">Subscriptions</th>
                <th className="num">Customers</th>
                <th className="num">MoM Change</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => {
                const prevRow = data[i - 1];
                const change =
                  prevRow
                    ? ((row.mrr_amount - prevRow.mrr_amount) / prevRow.mrr_amount) * 100
                    : null;
                return (
                  <tr key={row.month}>
                    <td className="month-cell">{row.month}</td>
                    <td className="num">{fmtCurrency(row.mrr_amount)}</td>
                    <td className="num">{row.active_subscriptions}</td>
                    <td className="num">{row.active_customers}</td>
                    <td
                      className="num"
                      style={{
                        color: change == null ? "#8a8f98" : change >= 0 ? "#059669" : "#dc2626",
                      }}
                    >
                      {fmtPct(change)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {error && (
        <div className="error-banner">
          <strong>API unavailable</strong> — showing demo data. Connect the Flask
          API to see live BigQuery data.
          <br />
          <code>{error}</code>
        </div>
      )}

      <footer className="footer">
        Built with Stripe API · BigQuery · React · Recharts
      </footer>
    </div>
  );
}

/* ---------- Demo/fallback data ---------- */
function getDemoData() {
  return [
    { month: "2025-09", mrr_amount: 4280, active_subscriptions: 52, active_customers: 48 },
    { month: "2025-10", mrr_amount: 5120, active_subscriptions: 58, active_customers: 53 },
    { month: "2025-11", mrr_amount: 5890, active_subscriptions: 62, active_customers: 56 },
    { month: "2025-12", mrr_amount: 6430, active_subscriptions: 65, active_customers: 59 },
    { month: "2026-01", mrr_amount: 7150, active_subscriptions: 70, active_customers: 63 },
    { month: "2026-02", mrr_amount: 7680, active_subscriptions: 73, active_customers: 66 },
  ];
}

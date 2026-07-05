import React, { useEffect, useState } from 'react';
import { Grid, Card, CardContent, Typography, Box, CircularProgress, Chip, Avatar } from '@mui/material';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import InventoryIcon from '@mui/icons-material/Inventory';
import ShoppingCartIcon from '@mui/icons-material/ShoppingCart';
import { getRevenueByCategory, getRevenueLast30Days, getTopProducts, getRealtimeTop } from '../api/client';
import ReplicaSet from '../components/ReplicaSet';

const COLORS = ['#6C63FF', '#FF6584', '#43E97B', '#F7971E', '#FEAC5E', '#4facfe', '#43e97b'];

function StatCard({ title, value, subtitle, icon, color }) {
  return (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <Box>
            <Typography variant="body2" color="text.secondary" gutterBottom>{title}</Typography>
            <Typography variant="h4" sx={{ fontWeight: 800, color }}>{value}</Typography>
            {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
          </Box>
          <Avatar sx={{ bgcolor: `${color}22`, color }}>
            {icon}
          </Avatar>
        </Box>
      </CardContent>
    </Card>
  );
}

export default function Dashboard() {
  const [catData,   setCatData]   = useState([]);
  const [last30,    setLast30]    = useState(null);
  const [topProds,  setTopProds]  = useState([]);
  const [topSales,  setTopSales]  = useState([]);
  const [loading,   setLoading]   = useState(true);

  useEffect(() => {
    Promise.all([
      getRevenueByCategory(),
      getRevenueLast30Days(),
      getTopProducts(5),
      getRealtimeTop(5),
    ]).then(([cat, l30, top, realtime]) => {
      
      const normalized = cat.data.categories.map(c => ({
        ...c,
        category: (c.category || "Autre")
          .replace("Electronique", "Électronique")
          .replace("Beaute", "Beauté")
      }));

      // Fusionner les doublons après normalisation
      const merged = {};
      normalized.forEach(c => {
        if (merged[c.category]) {
          merged[c.category].revenue += c.revenue;
          merged[c.category].tx_count += c.tx_count;
          merged[c.category].total_qty += c.total_qty;
        } else {
          merged[c.category] = { ...c };
        }
      });
      setCatData(Object.values(merged));
      setLast30(l30.data);
      setTopProds(top.data.products);
      setTopSales(realtime.data.top_sales);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
      <CircularProgress sx={{ color: 'primary.main' }} />
    </Box>
  );

  const totalCA   = catData.reduce((s, c) => s + c.revenue, 0);
  const totalTx   = catData.reduce((s, c) => s + c.tx_count, 0);
  const totalProds = catData.reduce((s, c) => s + c.unique_products, 0);

  return (
    <Box>
      {/* KPI Cards */}
      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={4}>
          <StatCard
            title="Chiffre d'affaires total"
            value={`${(totalCA / 1000000).toFixed(1)}M`}
            subtitle="Toutes catégories"
            icon={<TrendingUpIcon />}
            color="#6C63FF"
          />
        </Grid>
        <Grid item xs={12} sm={4}>
          <StatCard
            title="Transactions"
            value={totalTx.toLocaleString()}
            subtitle="Total traité"
            icon={<ShoppingCartIcon />}
            color="#FF6584"
          />
        </Grid>
        <Grid item xs={12} sm={4}>
          <StatCard
            title="Produits actifs"
            value={totalProds}
            subtitle="Dans le catalogue"
            icon={<InventoryIcon />}
            color="#43E97B"
          />
        </Grid>
      </Grid>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        {/* CA par catégorie - Bar chart */}
        <Grid item xs={12} md={7}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>CA par catégorie</Typography>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={catData}>
                  <XAxis dataKey="category" tick={{ fill: '#aaa', fontSize: 12 }} />
                  <YAxis tick={{ fill: '#aaa', fontSize: 11 }} tickFormatter={v => `${(v/1000).toFixed(0)}k`} />
                  <Tooltip
                    formatter={(v) => [`${v.toLocaleString()} XOF`, 'CA']}
                    contentStyle={{ bgcolor: '#1A1A2E', border: '1px solid #6C63FF33' }}
                  />
                  <Bar dataKey="revenue" radius={[6,6,0,0]}>
                    {catData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </Grid>

        {/* Répartition - Pie chart */}
        <Grid item xs={12} md={5}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>Répartition</Typography>
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie data={catData} dataKey="revenue" nameKey="category"
                    cx="50%" cy="50%" outerRadius={80} label={({ category, revenue_share_pct }) => `${revenue_share_pct}%`}>
                    {catData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Legend formatter={(v) => <span style={{ color: '#ccc', fontSize: 12 }}>{v}</span>} />
                  <Tooltip formatter={(v) => [`${v.toLocaleString()} XOF`]} />
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        {/* 30 derniers jours */}
        {last30 && (
          <Grid item xs={12} md={6}>
            <Card>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                  <Typography variant="h6">30 derniers jours</Typography>
                  <Chip label={`${last30.total_revenue.toLocaleString()} XOF`} color="primary" size="small" />
                </Box>
                {last30.categories.map((c, i) => (
                  <Box key={i} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.8,
                    borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: COLORS[i % COLORS.length] }} />
                      <Typography variant="body2">{c.category}</Typography>
                    </Box>
                    <Box sx={{ textAlign: 'right' }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>{c.revenue.toLocaleString()} XOF</Typography>
                      <Typography variant="caption" color="text.secondary">{c.tx_count} tx</Typography>
                    </Box>
                  </Box>
                ))}
              </CardContent>
            </Card>
          </Grid>
        )}

        {/* Top produits temps réel Redis */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6">Top ventes</Typography>
                <Chip label="Redis live" size="small" sx={{ bgcolor: 'rgba(255,101,132,0.15)', color: '#FF6584' }} />
              </Box>
              {topSales.map((p, i) => (
                <Box key={i} sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  py: 0.8, borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                    <Typography sx={{ color: 'primary.main', fontWeight: 800, fontSize: 13 }}>#{p.rank}</Typography>
                    <Typography variant="body2">{p.product_id}</Typography>
                  </Box>
                  <Typography variant="body2" sx={{ fontWeight: 600, color: '#43E97B' }}>
                    {p.revenue.toLocaleString()} XOF
                  </Typography>
                </Box>
              ))}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      <Box sx={{ mt: 3 }}>
        <ReplicaSet />
      </Box>
    </Box>
  );
}
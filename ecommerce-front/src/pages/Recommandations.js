import React, { useState } from 'react';
import { Box, Card, CardContent, Typography, TextField, Button, Grid,
  CircularProgress, Chip, Alert, ToggleButton, ToggleButtonGroup, Avatar } from '@mui/material';
import RecommendIcon from '@mui/icons-material/Recommend';
import PersonSearchIcon from '@mui/icons-material/PersonSearch';
import { getRecommendations, getCustomerOrders } from '../api/client';

export default function Recommandations() {
  const [customerId, setCustomerId] = useState('');
  const [depth,      setDepth]      = useState(3);
  const [recs,       setRecs]       = useState(null);
  const [orders,     setOrders]     = useState(null);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState('');

  const handleSearch = async () => {
    if (!customerId.trim()) return;
    setLoading(true);
    setError('');
    setRecs(null);
    setOrders(null);
    try {
      const [recRes, ordRes] = await Promise.all([
        getRecommendations(customerId, depth),
        getCustomerOrders(customerId),
      ]);
      setRecs(recRes.data);
      setOrders(ordRes.data);
    } catch (e) {
      if (e.response?.status === 404) {
        setError(`Aucune recommandation trouvée pour "${customerId}" à profondeur ${depth}. Essaie depth=3.`);
      } else {
        setError("Erreur lors de la requête.");
      }
    } finally {
      setLoading(false);
    }
  };

  const CATEGORY_COLORS = {
    'Mode': '#6C63FF', 'Sport': '#FF6584', 'Electronique': '#43E97B',
    'Maison': '#F7971E', 'Beaute': '#4facfe', 'Livres': '#FEAC5E', 'Autre': '#aaa'
  };

  return (
    <Box>
      {/* Recherche */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            Moteur de recommandation — Neo4j Cypher
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Algorithme collaboratif basé sur les comportements d'achat similaires (2-3 niveaux de profondeur)
          </Typography>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={12} md={5}>
              <TextField
                fullWidth
                placeholder="Ex: CUST-84177"
                label="ID Client"
                value={customerId}
                onChange={e => setCustomerId(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                size="small"
                InputProps={{
                  startAdornment: <PersonSearchIcon sx={{ mr: 1, color: 'primary.main' }} />
                }}
              />
            </Grid>
            <Grid item xs={12} md={3}>
              <Box>
                
                <ToggleButtonGroup
                  value={depth}
                  exclusive
                  onChange={(_, v) => v && setDepth(v)}
                  size="small"
                >
                  <ToggleButton value={2} sx={{ px: 3 }}>2 nœuds</ToggleButton>
                  <ToggleButton value={3} sx={{ px: 3 }}>3 nœuds</ToggleButton>
                </ToggleButtonGroup>
              </Box>
            </Grid>
            <Grid item xs={12} md={4}>
              <Button fullWidth variant="contained" onClick={handleSearch}
                disabled={loading} startIcon={<RecommendIcon />} sx={{ height: 40 }}>
                Trouver des recommandations
              </Button>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
          <CircularProgress sx={{ color: 'primary.main' }} />
        </Box>
      )}

      {error && <Alert severity="warning" sx={{ mb: 2 }}>{error}</Alert>}

      {orders && recs && (
        <Grid container spacing={2}>
          {/* Profil client */}
          <Grid item xs={12} md={4}>
            <Card>
              <CardContent>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
                  <Avatar sx={{ bgcolor: 'primary.main', width: 48, height: 48 }}>
                    {customerId.slice(-2)}
                  </Avatar>
                  <Box>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{customerId}</Typography>
                    <Typography variant="caption" color="text.secondary">Profil client</Typography>
                  </Box>
                </Box>

                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                    <Typography variant="body2" color="text.secondary">Commandes</Typography>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {orders.stats?.order_count}
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                    <Typography variant="body2" color="text.secondary">Total dépensé</Typography>
                    <Typography variant="body2" sx={{ fontWeight: 600, color: '#43E97B' }}>
                      {orders.stats?.total_spent?.toLocaleString()} XOF
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                    <Typography variant="body2" color="text.secondary">Panier moyen</Typography>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>
                      {orders.stats?.avg_basket?.toFixed(0)} XOF
                    </Typography>
                  </Box>
                </Box>

                <Box sx={{ mt: 2 }}>
                  <Typography variant="caption" color="text.secondary" gutterBottom>Catégories achetées</Typography>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                    {orders.stats?.categories?.map((c, i) => (
                      <Chip key={i} label={c} size="small" sx={{
                        bgcolor: `${CATEGORY_COLORS[c] || '#aaa'}22`,
                        color: CATEGORY_COLORS[c] || '#aaa',
                        fontSize: 10
                      }} />
                    ))}
                  </Box>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* Recommandations */}
          <Grid item xs={12} md={8}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Typography variant="h6">
                Produits recommandés
              </Typography>
              <Chip
                label={`Profondeur ${recs.algorithm_depth} nœuds`}
                size="small"
                sx={{ bgcolor: 'rgba(108,99,255,0.15)', color: 'primary.main' }}
              />
            </Box>

            <Grid container spacing={1.5}>
              {recs.recommendations.map((r, i) => (
                <Grid item xs={12} sm={6} key={i}>
                  <Card sx={{
                    '&:hover': { borderColor: 'primary.main', transition: '0.2s' },
                    position: 'relative', overflow: 'visible'
                  }}>
                    <Box sx={{
                      position: 'absolute', top: -10, left: 12,
                      bgcolor: 'primary.main', borderRadius: 1,
                      px: 1, py: 0.2, fontSize: 11, fontWeight: 800, color: '#fff'
                    }}>
                      #{i + 1}
                    </Box>
                    <CardContent sx={{ pt: 2.5 }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <Box>
                          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>{r.product_id}</Typography>
                          <Chip label={r.category} size="small" sx={{
                            mt: 0.5, fontSize: 10,
                            bgcolor: `${CATEGORY_COLORS[r.category] || '#aaa'}22`,
                            color: CATEGORY_COLORS[r.category] || '#aaa'
                          }} />
                        </Box>
                        <Box sx={{ textAlign: 'right' }}>
                          <Typography variant="caption" color="text.secondary">Score</Typography>
                          <Typography variant="h6" sx={{ color: 'primary.main', fontWeight: 800, lineHeight: 1 }}>
                            {r.relevance_score}
                          </Typography>
                        </Box>
                      </Box>
                      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                        Recommandé par {r.recommended_by_n_customers} client(s) similaire(s)
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>
          </Grid>
        </Grid>
      )}
    </Box>
  );
}
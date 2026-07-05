import React, { useState } from 'react';
import { Box, Card, CardContent, Typography, TextField, Grid, Chip, CircularProgress,
  InputAdornment, Slider, Button, Divider, Alert } from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import FilterListIcon from '@mui/icons-material/FilterList';
import { searchCatalogue } from '../api/client';

export default function Catalogue() {
  const [query,    setQuery]    = useState('');
  const [results,  setResults]  = useState(null);
  const [facettes, setFacettes] = useState(null);
  const [loading,  setLoading]  = useState(false);
  const [prix,     setPrix]     = useState([0, 500]);
  const [catFilter, setCatFilter] = useState('');
  const [error,    setError]    = useState('');

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setError('');
    try {
      const res = await searchCatalogue(query, catFilter || null, prix[0] || null, prix[1] || null);
      setResults(res.data.resultats);
      setFacettes(res.data.facettes);
    } catch (e) {
      setError("Erreur lors de la recherche.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box>
      {/* Barre de recherche */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>Recherche textuelle avec facettes</Typography>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={12} md={6}>
              <TextField
                fullWidth
                placeholder="Rechercher un produit, marque, tag..."
                value={query}
                onChange={e => setQuery(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                InputProps={{
                  startAdornment: <InputAdornment position="start"><SearchIcon sx={{ color: 'primary.main' }} /></InputAdornment>
                }}
                size="small"
              />
            </Grid>
            <Grid item xs={12} md={4}>
              <Typography variant="caption" color="text.secondary">
                Tranche de prix : {prix[0]} — {prix[1]} XOF
              </Typography>
              <Slider
                value={prix}
                onChange={(_, v) => setPrix(v)}
                min={0} max={500} step={10}
                sx={{ color: 'primary.main' }}
              />
            </Grid>
            <Grid item xs={12} md={2}>
              <Button fullWidth variant="contained" onClick={handleSearch}
                startIcon={<FilterListIcon />} disabled={loading}>
                Chercher
              </Button>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
          <CircularProgress sx={{ color: 'primary.main' }} />
        </Box>
      )}

      {results && (
        <Grid container spacing={2}>
          {/* Facettes */}
          <Grid item xs={12} md={3}>
            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom sx={{ color: 'primary.main' }}>
                  Catégories
                </Typography>
                {facettes?.categories?.map((f, i) => (
                  <Box key={i} sx={{ display: 'flex', justifyContent: 'space-between',
                    py: 0.5, cursor: 'pointer' }}
                    onClick={() => { setCatFilter(f.categorie === catFilter ? '' : f.categorie); }}>
                    <Typography variant="body2" sx={{
                      color: catFilter === f.categorie ? 'primary.main' : 'text.primary'
                    }}>
                      {f.categorie}
                    </Typography>
                    <Chip label={f.count} size="small" sx={{ height: 18, fontSize: 10 }} />
                  </Box>
                ))}

                <Divider sx={{ my: 2 }} />

                <Typography variant="subtitle2" gutterBottom sx={{ color: 'primary.main' }}>
                  Tranches de prix
                </Typography>
                {facettes?.prix?.map((f, i) => (
                  <Box key={i} sx={{ display: 'flex', justifyContent: 'space-between', py: 0.5 }}>
                    <Typography variant="body2">{f.tranche} XOF</Typography>
                    <Chip label={f.count} size="small" sx={{ height: 18, fontSize: 10 }} />
                  </Box>
                ))}
              </CardContent>
            </Card>
          </Grid>

          {/* Résultats */}
          <Grid item xs={12} md={9}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {results.length} résultat(s) pour "<b>{query}</b>"
            </Typography>
            <Grid container spacing={2}>
              {results.length === 0 ? (
                <Grid item xs={12}>
                  <Alert severity="info">Aucun produit trouvé pour cette recherche.</Alert>
                </Grid>
              ) : results.map((p, i) => (
                <Grid item xs={12} sm={6} lg={4} key={i}>
                  <Card sx={{ height: '100%', '&:hover': { borderColor: 'primary.main', transition: '0.2s' } }}>
                    <CardContent>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                        <Chip label={p.categorie} size="small" sx={{
                          bgcolor: 'rgba(108,99,255,0.15)', color: 'primary.main', fontSize: 10
                        }} />
                        <Typography variant="caption" color="text.secondary">{p.product_id}</Typography>
                      </Box>
                      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>{p.nom}</Typography>
                      <Typography variant="caption" color="text.secondary">{p.marque}</Typography>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 1.5 }}>
                        <Typography variant="h6" sx={{ color: '#43E97B', fontWeight: 800 }}>
                          {p.prix_base?.toLocaleString()} XOF
                        </Typography>
                        <Box sx={{ textAlign: 'right' }}>
                          <Typography variant="caption" color="text.secondary">
                            ⭐ {p.note_moyenne}
                          </Typography>
                          <br />
                          <Typography variant="caption" color="text.secondary">
                            {p.nb_variants} variantes
                          </Typography>
                        </Box>
                      </Box>
                      <Box sx={{ mt: 1 }}>
                        <Chip
                          label={`Stock: ${p.stock_total}`}
                          size="small"
                          sx={{ fontSize: 10, bgcolor: p.stock_total > 0 ? 'rgba(67,233,123,0.1)' : 'rgba(255,101,132,0.1)',
                            color: p.stock_total > 0 ? '#43E97B' : '#FF6584' }}
                        />
                      </Box>
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
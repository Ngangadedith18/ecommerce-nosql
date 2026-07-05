import React, { useState, useRef, useEffect } from 'react';
import {
  Box, Card, CardContent, Typography, Button, CircularProgress,
  Alert, Chip, LinearProgress, ToggleButton, ToggleButtonGroup
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import axios from 'axios';

const API = axios.create({ baseURL: 'http://localhost:8000' });

export default function Pipeline() {
  const [mode,    setMode]    = useState('direct');
  const [file,    setFile]    = useState(null);
  const [started, setStarted] = useState(false);
  const [running, setRunning] = useState(false);
  const [result,  setResult]  = useState(null);
  const [error,   setError]   = useState('');
  const [elapsed, setElapsed] = useState(0);
  const fileRef    = useRef();
  const pollRef    = useRef(null);
  const timerRef   = useRef(null);

  // Polling toutes les 5 secondes
  const startPolling = () => {
    pollRef.current = setInterval(async () => {
      try {
        const res = await API.get('/pipeline/status');
        const data = res.data;
        if (!data.running && data.result !== null) {
          setResult(data.result);
          setRunning(false);
          stopPolling();
        }
      } catch (e) {
        // ignore
      }
    }, 5000);
  };

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  };

  useEffect(() => () => stopPolling(), []);

  useEffect(() => {
    API.get('/pipeline/status').then(res => {
        if (res.data.running) {
        setStarted(true);
        setRunning(true);
        startPolling();
        } else if (res.data.result) {
        setStarted(true);
        setResult(res.data.result);
        }
    }).catch(() => {});
  }, []);

  const handleRun = async () => {
    setStarted(true);
    setRunning(true);
    setResult(null);
    setError('');
    setElapsed(0);

    // Chrono
    timerRef.current = setInterval(() => setElapsed(e => e + 1), 1000);

    try {
      if (mode === 'upload' && file) {
        const form = new FormData();
        form.append('file', file);
        await API.post('/pipeline/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } });
      } else {
        await API.post('/pipeline/run');
      }
      startPolling();
    } catch (e) {
      setError(e.response?.data?.detail || "Erreur lors du lancement.");
      setRunning(false);
      setStarted(false);
      stopPolling();
    }
  };

  const handleReset = () => {
    setStarted(false);
    setResult(null);
    setError('');
    setElapsed(0);
    setFile(null);
    stopPolling();
  };

  const parseStats = (stdout) => {
    if (!stdout) return null;
    const stats = {};
    const patterns = [
      { key: 'total_raw',    label: 'Lignes brutes',        regex: /total_raw\s+:\s+([\d,]+)/ },
      { key: 'duplicates',   label: 'Doublons supprimés',   regex: /duplicates\s+:\s+([\d,]+)/ },
      { key: 'bad_date',     label: 'Dates invalides',      regex: /bad_date\s+:\s+([\d,]+)/ },
      { key: 'bad_price',    label: 'Prix corrompus',       regex: /bad_price\s+:\s+([\d,]+)/ },
      { key: 'bad_quantity', label: 'Quantités invalides',  regex: /bad_quantity\s+:\s+([\d,]+)/ },
      { key: 'anonymous',    label: 'Anonymes',             regex: /anonymous\s+:\s+([\d,]+)/ },
      { key: 'clean',        label: 'Transactions propres', regex: /clean\s+:\s+([\d,]+)/ },
    ];
    patterns.forEach(({ key, label, regex }) => {
      const m = stdout.match(regex);
      if (m) stats[key] = { label, value: m[1] };
    });
    return Object.keys(stats).length > 0 ? stats : null;
  };

  const stats  = result ? parseStats(result.stdout) : null;
  const canRun = mode === 'direct' || (mode === 'upload' && file !== null);
  const mins   = Math.floor(elapsed / 60);
  const secs   = elapsed % 60;

  return (
    <Box>
      {/* Carte principale */}
      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>Pipeline de nettoyage et d'injection</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Nettoie les données brutes et injecte en masse dans MongoDB, Neo4j et Redis.
            Le pipeline tourne en arrière-plan — le dashboard reste accessible pendant l'exécution.
          </Typography>

          {/* Mode */}
          {!started && (
            <>
              <Box sx={{ mb: 3 }}>
                <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                  Source des données
                </Typography>
                <ToggleButtonGroup value={mode} exclusive size="small"
                  onChange={(_, v) => { if (v) { setMode(v); setFile(null); } }}>
                  <ToggleButton value="direct" sx={{ px: 3 }}>CSV sur le serveur</ToggleButton>
                  <ToggleButton value="upload" sx={{ px: 3 }}>Uploader un CSV</ToggleButton>
                </ToggleButtonGroup>
              </Box>

              {mode === 'upload' && (
                <Box sx={{ mb: 3 }}>
                  <input ref={fileRef} type="file" accept=".csv" style={{ display: 'none' }}
                    onChange={e => setFile(e.target.files[0] || null)} />
                  <Box onClick={() => fileRef.current.click()} sx={{
                    border: '2px dashed', borderColor: file ? 'primary.main' : 'rgba(108,99,255,0.3)',
                    borderRadius: 2, p: 3, textAlign: 'center', cursor: 'pointer',
                    bgcolor: file ? 'rgba(108,99,255,0.05)' : 'transparent',
                    '&:hover': { borderColor: 'primary.main', bgcolor: 'rgba(108,99,255,0.05)' }
                  }}>
                    {file ? (
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1 }}>
                        <InsertDriveFileIcon sx={{ color: 'primary.main' }} />
                        <Typography variant="body2" sx={{ color: 'primary.main', fontWeight: 600 }}>
                          {file.name} ({(file.size / 1024 / 1024).toFixed(1)} Mo)
                        </Typography>
                      </Box>
                    ) : (
                      <Box>
                        <UploadFileIcon sx={{ fontSize: 36, color: 'text.secondary', mb: 1 }} />
                        <Typography variant="body2" color="text.secondary">
                          Cliquez pour sélectionner votre CSV
                        </Typography>
                      </Box>
                    )}
                  </Box>
                </Box>
              )}

              <Button variant="contained" size="large"
                startIcon={<PlayArrowIcon />}
                onClick={handleRun} disabled={!canRun}
                sx={{ minWidth: 220 }}>
                Lancer le pipeline
              </Button>
            </>
          )}

          {/* En cours */}
          {running && (
            <Box>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
                <HourglassEmptyIcon sx={{ color: 'primary.main' }} />
                <Typography variant="body1" sx={{ fontWeight: 600 }}>
                  Pipeline en cours... {mins > 0 ? `${mins}m ` : ''}{secs}s
                </Typography>
                <Chip label="En arrière-plan" size="small"
                  sx={{ bgcolor: 'rgba(108,99,255,0.15)', color: 'primary.main' }} />
              </Box>
              <LinearProgress sx={{ borderRadius: 1, mb: 1 }} />
              <Typography variant="caption" color="text.secondary">
                Vérification toutes les 5 secondes — vous pouvez naviguer sur le Dashboard pendant ce temps.
              </Typography>
            </Box>
          )}
        </CardContent>
      </Card>

      {/* Erreur */}
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {/* Résultat */}
      {result && (
        <Box>
          <Card sx={{ mb: 2 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
                {result.status === 'success'
                  ? <CheckCircleIcon sx={{ color: '#43E97B', fontSize: 28 }} />
                  : <ErrorIcon sx={{ color: '#FF6584', fontSize: 28 }} />}
                <Typography variant="h6">
                  {result.status === 'success' ? 'Pipeline terminé avec succès' : 'Pipeline terminé avec erreurs'}
                </Typography>
                <Chip label={`${mins}m ${secs}s`} size="small" sx={{ bgcolor: 'rgba(108,99,255,0.15)', color: 'primary.main' }} />
              </Box>
              <Button variant="outlined" size="small" onClick={handleReset} sx={{ mt: 1 }}>
                Nouveau pipeline
              </Button>
            </CardContent>
          </Card>

          {stats && (
            <Card sx={{ mb: 2 }}>
              <CardContent>
                <Typography variant="h6" gutterBottom>Bilan nettoyage</Typography>
                <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 1.5 }}>
                  {Object.entries(stats).map(([key, { label, value }]) => (
                    <Box key={key} sx={{
                      p: 1.5, borderRadius: 1,
                      bgcolor: key === 'clean' ? 'rgba(67,233,123,0.08)' :
                               key === 'total_raw' ? 'rgba(108,99,255,0.08)' : 'rgba(255,101,132,0.05)',
                      border: '1px solid',
                      borderColor: key === 'clean' ? 'rgba(67,233,123,0.2)' :
                                   key === 'total_raw' ? 'rgba(108,99,255,0.2)' : 'rgba(255,101,132,0.1)',
                    }}>
                      <Typography variant="caption" color="text.secondary">{label}</Typography>
                      <Typography variant="h6" sx={{
                        fontWeight: 800,
                        color: key === 'clean' ? '#43E97B' : key === 'total_raw' ? 'primary.main' : 'text.primary'
                      }}>{value}</Typography>
                    </Box>
                  ))}
                </Box>
              </CardContent>
            </Card>
          )}

          {result.stdout && (
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>Logs</Typography>
                <Box sx={{ bgcolor: '#0F172A', borderRadius: 1, p: 2, maxHeight: 400, overflowY: 'auto',
                  border: '1px solid rgba(108,99,255,0.2)' }}>
                  <pre style={{ margin: 0, fontSize: 11, color: '#7DD3FC',
                    fontFamily: 'Courier New, monospace', whiteSpace: 'pre-wrap' }}>
                    {result.stdout}
                  </pre>
                </Box>
                {result.stderr && (
                <Box sx={{ bgcolor: '#1A0000', borderRadius: 1, p: 2, mt: 2,
                    border: '1px solid rgba(255,101,132,0.2)' }}>
                    <Typography variant="caption" color="error">Erreurs stderr :</Typography>
                    <pre style={{ margin: 0, fontSize: 11, color: '#FF6584',
                    fontFamily: 'Courier New, monospace', whiteSpace: 'pre-wrap' }}>
                    {result.stderr}
                    </pre>
                </Box>
                )}
              </CardContent>
            </Card>
          )}
        </Box>
      )}
    </Box>
  );
}
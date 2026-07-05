import React, { useState, useEffect } from 'react';
import { Box, Card, CardContent, Typography, Chip, CircularProgress } from '@mui/material';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import axios from 'axios';

const API = axios.create({ baseURL: 'http://localhost:8000' });

const STATE_COLORS = {
  PRIMARY:   { bg: 'rgba(67,233,123,0.1)',  border: '#43E97B', text: '#43E97B' },
  SECONDARY: { bg: 'rgba(37,99,235,0.1)',   border: '#2563EB', text: '#2563EB' },
  ARBITER:   { bg: 'rgba(217,119,6,0.1)',   border: '#D97706', text: '#D97706' },
  DOWN:      { bg: 'rgba(255,101,132,0.1)', border: '#FF6584', text: '#FF6584' },
  UNKNOWN:   { bg: 'rgba(100,116,139,0.1)', border: '#64748B', text: '#64748B' },
};

function getColor(state) {
  return STATE_COLORS[state] || STATE_COLORS.UNKNOWN;
}

function formatUptime(seconds) {
  if (!seconds) return '-';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

export default function ReplicaSet() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [prev,    setPrev]    = useState(null); // état précédent pour détecter les changements
  const [changed, setChanged] = useState(null); // nœud qui a changé

  const fetchStatus = async () => {
    try {
      const res = await API.get('/mongodb/replicaset');
      const newData = res.data;

      // Détecter les changements de rôle
      if (data && data.members) {
        newData.members.forEach(m => {
          const old = data.members.find(om => om.name === m.name);
          if (old && old.state !== m.state) {
            setChanged({ name: m.name, from: old.state, to: m.state });
            setTimeout(() => setChanged(null), 5000);
          }
        });
      }

      setPrev(data);
      setData(newData);
    } catch (e) {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, []);

  if (loading) return (
    <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
      <CircularProgress size={24} />
    </Box>
  );

  if (!data) return null;

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6">
            Replica Set — {data.replicaSet}
          </Typography>
          <Chip
            icon={<FiberManualRecordIcon sx={{ fontSize: '10px !important', color: '#43E97B !important' }} />}
            label="Live — toutes les 3s"
            size="small"
            sx={{ bgcolor: 'rgba(67,233,123,0.1)', color: '#43E97B', border: '1px solid rgba(67,233,123,0.3)' }}
          />
        </Box>

        {/* Alerte changement de rôle */}
        {changed && (
          <Box sx={{
            mb: 2, p: 1.5, borderRadius: 1,
            bgcolor: 'rgba(217,119,6,0.1)', border: '1px solid #D97706'
          }}>
            <Typography variant="body2" sx={{ color: '#D97706', fontWeight: 600 }}>
              ⚡ Failover détecté : {changed.name} est passé de {changed.from} à {changed.to}
            </Typography>
          </Box>
        )}

        {/* Nœuds */}
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
          {data.members.map((m, i) => {
            const c = getColor(m.state);
            const isPrimary = m.state === 'PRIMARY';
            return (
              <Box key={i} sx={{
                flex: 1, minWidth: 180,
                p: 2, borderRadius: 2,
                bgcolor: c.bg,
                border: `2px solid ${c.border}`,
                transition: 'all 0.5s ease',
                boxShadow: isPrimary ? `0 0 12px ${c.border}44` : 'none',
              }}>
                {/* Nom du nœud */}
                <Typography variant="subtitle2" sx={{ fontWeight: 700, color: c.text, mb: 0.5 }}>
                  {m.name.split(':')[0]}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  :{m.name.split(':')[1]}
                </Typography>

                {/* Badge état */}
                <Box sx={{ mt: 1.5, mb: 1 }}>
                  <Chip
                    label={m.state}
                    size="small"
                    sx={{
                      bgcolor: c.border,
                      color: '#fff',
                      fontWeight: 700,
                      fontSize: 11,
                    }}
                  />
                </Box>

                {/* Uptime */}
                <Typography variant="caption" color="text.secondary">
                  Uptime : {formatUptime(m.uptime)}
                </Typography>

                {/* Indicateur santé */}
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 0.5 }}>
                  <FiberManualRecordIcon sx={{
                    fontSize: 10,
                    color: m.health === 1 ? '#43E97B' : '#FF6584'
                  }} />
                  <Typography variant="caption" color="text.secondary">
                    {m.health === 1 ? 'En ligne' : 'Hors ligne'}
                  </Typography>
                </Box>
              </Box>
            );
          })}
        </Box>
      </CardContent>
    </Card>
  );
}